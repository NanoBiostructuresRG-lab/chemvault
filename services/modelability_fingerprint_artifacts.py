# SPDX-License-Identifier: LGPL-3.0-or-later
"""SQLite persistence for Modelability fingerprint matrix artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import numpy.typing as npt


FINGERPRINT_ARTIFACTS_TABLE = (
    "_chemvault_modelability_fingerprint_artifacts"
)
MATRIX_FORMAT = "npy-zlib"
MATRIX_FORMAT_VERSION = 1
MATRIX_DTYPE = "uint8"


class FingerprintArtifactError(ValueError):
    """Raised when a persisted fingerprint artifact cannot be used."""


@dataclass(frozen=True)
class FingerprintArtifactExpectation:
    source_table: str
    fingerprint_identity: str
    artifact_contract: str
    artifact_contract_version: int
    population_identity: str
    profile: Mapping[str, object]
    profile_hash: str
    ordered_input_hash: str
    molraptor_version: str
    rdkit_version: str
    ordered_smiles: tuple[str, ...]
    row_count: int
    fp_size: int


@dataclass(frozen=True)
class FingerprintArtifact:
    matrix: npt.NDArray[np.uint8]
    ordered_smiles: tuple[str, ...]
    sha256: str
    profile: Mapping[str, object]
    profile_hash: str
    ordered_input_hash: str
    molraptor_version: str
    rdkit_version: str


def _canonical_json(value: object, *, sort_keys: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    )


def _ordered_smiles_json(ordered_smiles: Sequence[str]) -> str:
    return _canonical_json(list(ordered_smiles))


def _matrix_npy_bytes(matrix) -> tuple[npt.NDArray[np.uint8], bytes]:
    array = np.asarray(matrix)
    if array.dtype != np.dtype(np.uint8):
        raise ValueError("Fingerprint matrix dtype must be uint8.")
    normalized = np.ascontiguousarray(array)
    if not np.all((normalized == 0) | (normalized == 1)):
        raise ValueError("Fingerprint matrix values must be binary.")
    stream = io.BytesIO()
    np.save(stream, normalized, allow_pickle=False)
    return normalized, stream.getvalue()


def _artifact_checksum(ordered_smiles_json: str, npy_payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(ordered_smiles_json.encode("utf-8"))
    digest.update(b"\0")
    digest.update(npy_payload)
    return digest.hexdigest()


def build_fingerprint_artifact(
    matrix,
    ordered_smiles: Sequence[str],
    *,
    profile: Mapping[str, object],
    profile_hash: str,
    ordered_input_hash: str,
    molraptor_version: str,
    rdkit_version: str,
) -> FingerprintArtifact:
    ordered_smiles = tuple(ordered_smiles)
    normalized, npy_payload = _matrix_npy_bytes(matrix)
    checksum = _artifact_checksum(
        _ordered_smiles_json(ordered_smiles),
        npy_payload,
    )
    return FingerprintArtifact(
        matrix=normalized,
        ordered_smiles=ordered_smiles,
        sha256=checksum,
        profile=dict(profile),
        profile_hash=str(profile_hash),
        ordered_input_hash=str(ordered_input_hash),
        molraptor_version=str(molraptor_version),
        rdkit_version=str(rdkit_version),
    )


def _ensure_artifacts_table(connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FINGERPRINT_ARTIFACTS_TABLE} (
            source_table TEXT NOT NULL,
            fingerprint_identity TEXT NOT NULL,
            artifact_contract TEXT NOT NULL,
            artifact_contract_version INTEGER NOT NULL,
            population_identity TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            profile_hash TEXT NOT NULL,
            ordered_input_hash TEXT NOT NULL,
            molraptor_version TEXT NOT NULL,
            rdkit_version TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            fp_size INTEGER NOT NULL,
            matrix_format TEXT NOT NULL,
            matrix_format_version INTEGER NOT NULL,
            matrix_dtype TEXT NOT NULL,
            ordered_smiles_json TEXT NOT NULL,
            matrix_payload BLOB NOT NULL,
            checksum TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (source_table, fingerprint_identity)
        )
        """
    )


def _restore_artifact(
    connection,
    expected: FingerprintArtifactExpectation,
) -> FingerprintArtifact | None:
    row = connection.execute(
        f"""
        SELECT
            source_table,
            fingerprint_identity,
            artifact_contract,
            artifact_contract_version,
            population_identity,
            profile_json,
            profile_hash,
            ordered_input_hash,
            molraptor_version,
            rdkit_version,
            row_count,
            fp_size,
            matrix_format,
            matrix_format_version,
            matrix_dtype,
            ordered_smiles_json,
            matrix_payload,
            checksum,
            created_at
        FROM {FINGERPRINT_ARTIFACTS_TABLE}
        WHERE source_table = ? AND fingerprint_identity = ?
        """,
        (expected.source_table, expected.fingerprint_identity),
    ).fetchone()
    if row is None:
        return None

    expected_profile_json = _canonical_json(expected.profile, sort_keys=True)
    expected_smiles_json = _ordered_smiles_json(expected.ordered_smiles)
    expected_shape = (expected.row_count, expected.fp_size)
    if (
        row[0] != expected.source_table
        or row[1] != expected.fingerprint_identity
        or row[2] != expected.artifact_contract
        or row[3] != expected.artifact_contract_version
        or row[4] != expected.population_identity
        or row[5] != expected_profile_json
        or row[6] != expected.profile_hash
        or row[7] != expected.ordered_input_hash
        or row[8] != expected.molraptor_version
        or row[9] != expected.rdkit_version
        or row[10] != expected.row_count
        or row[11] != expected.fp_size
        or row[12] != MATRIX_FORMAT
        or row[13] != MATRIX_FORMAT_VERSION
        or row[14] != MATRIX_DTYPE
        or row[15] != expected_smiles_json
    ):
        return None

    try:
        created_at = datetime.fromisoformat(row[18])
        if created_at.tzinfo is None:
            return None
        npy_payload = zlib.decompress(row[16])
        if _artifact_checksum(expected_smiles_json, npy_payload) != row[17]:
            return None
        stream = io.BytesIO(npy_payload)
        matrix = np.load(stream, allow_pickle=False)
        if stream.tell() != len(npy_payload):
            return None
    except (TypeError, ValueError, OSError, zlib.error):
        return None

    if (
        matrix.shape != expected_shape
        or matrix.dtype != np.dtype(np.uint8)
        or not matrix.flags.c_contiguous
        or not np.all((matrix == 0) | (matrix == 1))
    ):
        return None
    return FingerprintArtifact(
        matrix=matrix,
        ordered_smiles=expected.ordered_smiles,
        sha256=row[17],
        profile=dict(expected.profile),
        profile_hash=row[6],
        ordered_input_hash=row[7],
        molraptor_version=row[8],
        rdkit_version=row[9],
    )


def _artifact_matches_expectation(
    artifact: FingerprintArtifact,
    expected: FingerprintArtifactExpectation,
) -> bool:
    return (
        artifact.ordered_smiles == expected.ordered_smiles
        and artifact.matrix.shape == (expected.row_count, expected.fp_size)
        and artifact.matrix.dtype == np.dtype(np.uint8)
        and artifact.matrix.flags.c_contiguous
        and np.all((artifact.matrix == 0) | (artifact.matrix == 1))
        and _canonical_json(artifact.profile, sort_keys=True)
        == _canonical_json(expected.profile, sort_keys=True)
        and artifact.profile_hash == expected.profile_hash
        and artifact.ordered_input_hash == expected.ordered_input_hash
        and artifact.molraptor_version == expected.molraptor_version
        and artifact.rdkit_version == expected.rdkit_version
    )


def _replace_artifact(
    connection,
    expected: FingerprintArtifactExpectation,
    artifact: FingerprintArtifact,
) -> FingerprintArtifact:
    matrix, npy_payload = _matrix_npy_bytes(artifact.matrix)
    ordered_smiles_json = _ordered_smiles_json(expected.ordered_smiles)
    checksum = _artifact_checksum(ordered_smiles_json, npy_payload)
    stored = FingerprintArtifact(
        matrix=matrix,
        ordered_smiles=expected.ordered_smiles,
        sha256=checksum,
        profile=dict(expected.profile),
        profile_hash=expected.profile_hash,
        ordered_input_hash=expected.ordered_input_hash,
        molraptor_version=expected.molraptor_version,
        rdkit_version=expected.rdkit_version,
    )
    connection.execute(
        f"""
        INSERT INTO {FINGERPRINT_ARTIFACTS_TABLE} (
            source_table,
            fingerprint_identity,
            artifact_contract,
            artifact_contract_version,
            population_identity,
            profile_json,
            profile_hash,
            ordered_input_hash,
            molraptor_version,
            rdkit_version,
            row_count,
            fp_size,
            matrix_format,
            matrix_format_version,
            matrix_dtype,
            ordered_smiles_json,
            matrix_payload,
            checksum,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_table, fingerprint_identity) DO UPDATE SET
            artifact_contract = excluded.artifact_contract,
            artifact_contract_version = excluded.artifact_contract_version,
            population_identity = excluded.population_identity,
            profile_json = excluded.profile_json,
            profile_hash = excluded.profile_hash,
            ordered_input_hash = excluded.ordered_input_hash,
            molraptor_version = excluded.molraptor_version,
            rdkit_version = excluded.rdkit_version,
            row_count = excluded.row_count,
            fp_size = excluded.fp_size,
            matrix_format = excluded.matrix_format,
            matrix_format_version = excluded.matrix_format_version,
            matrix_dtype = excluded.matrix_dtype,
            ordered_smiles_json = excluded.ordered_smiles_json,
            matrix_payload = excluded.matrix_payload,
            checksum = excluded.checksum,
            created_at = excluded.created_at
        """,
        (
            expected.source_table,
            expected.fingerprint_identity,
            expected.artifact_contract,
            expected.artifact_contract_version,
            expected.population_identity,
            _canonical_json(expected.profile, sort_keys=True),
            expected.profile_hash,
            expected.ordered_input_hash,
            expected.molraptor_version,
            expected.rdkit_version,
            expected.row_count,
            expected.fp_size,
            MATRIX_FORMAT,
            MATRIX_FORMAT_VERSION,
            MATRIX_DTYPE,
            ordered_smiles_json,
            zlib.compress(npy_payload),
            checksum,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    connection.commit()
    return stored


def restore_or_calculate_fingerprint_artifact(
    connection,
    *,
    expectation: FingerprintArtifactExpectation,
    calculate: Callable[[], FingerprintArtifact],
) -> tuple[FingerprintArtifact, str]:
    """Restore a validated artifact or calculate and atomically replace it."""
    _ensure_artifacts_table(connection)
    restored = _restore_artifact(connection, expectation)
    if restored is not None:
        return restored, "restored"

    calculated = calculate()
    if not _artifact_matches_expectation(calculated, expectation):
        raise ValueError("Calculated fingerprint artifact is incompatible.")
    return _replace_artifact(connection, expectation, calculated), "calculated"


def read_fingerprint_artifact(
    connection,
    *,
    expectation: FingerprintArtifactExpectation,
) -> FingerprintArtifact:
    """Read one existing compatible artifact without creating or replacing it."""
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (FINGERPRINT_ARTIFACTS_TABLE,),
        ).fetchone()
        artifact = (
            _restore_artifact(connection, expectation)
            if table_exists is not None
            else None
        )
    except sqlite3.Error as error:
        raise FingerprintArtifactError(
            "The persisted fingerprint artifact is unavailable or incompatible."
        ) from error
    if artifact is None:
        raise FingerprintArtifactError(
            "The persisted fingerprint artifact is missing, corrupt, or incompatible."
        )
    return artifact

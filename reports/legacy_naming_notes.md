# Legacy Naming Notes

This document records legacy names that remain in ChemVault after the app-shell
refactor. These names should not be renamed casually because several of them
are Streamlit session-state keys, public service function names, test fixtures,
or filesystem paths used by existing workflows.

## Current Legacy Names To Preserve

| Name | Location | Current role | Why it remains |
| --- | --- | --- | --- |
| `grupo_a_contar` | `state_keys.GROUP_COUNT_COLUMN` | Session-state key for the group-count column selector | Changing the string key would reset or break existing Streamlit state behavior. |
| `depurado_success_table` | `state_keys.DEPURADO_SUCCESS_TABLE` | Session-state key for Refine success feedback | Existing key value is part of the current UI state contract. |
| `depurado_success_message` | `state_keys.DEPURADO_SUCCESS_MESSAGE` | Session-state key for Refine success messaging | Existing key value is part of the current UI state contract. |
| `codigo_buscar` | `state_keys.CODIGO_BUSCAR` | Session-state key for subgroup export search value | Existing key value is used by Export UI state. |
| `agregar_df_por_pk` | `services.curation` | Merge a dataframe into the active table by key | Tests and sidebar curation flow call this name directly. |
| `export_table_by_sub_grupo` | `services.export` | Export filtered subgroup CSV data | Existing tests and sidebar export flow call this function directly. |
| `columna_filtro` | `services.export.export_table_by_sub_grupo` | Parameter for the export filter column | Existing call sites and tests use this parameter name. |
| `_set_curados_false` | `ui.sidebar` | Reset HARMONSMILE/CHAMANP UI selection state | Private helper, but it preserves the historical Curate naming. |
| `tempFilesHarmonsile` | `app.verify_directories` | Directory required by the existing HARMONSMILE-related file workflow | The spelling appears to be historical and may be expected by external code. |

## Preferred New Names For Future Migration

These names are clearer, but should be introduced only through a compatibility
layer and tests:

| Legacy name | Suggested future name |
| --- | --- |
| `grupo_a_contar` | `group_count_column` |
| `depurado_success_table` | `refine_success_table` |
| `depurado_success_message` | `refine_success_message` |
| `codigo_buscar` | `export_filter_value` |
| `agregar_df_por_pk` | `merge_dataframe_by_key` |
| `export_table_by_sub_grupo` | `export_table_by_subgroup` |
| `columna_filtro` | `filter_column` |
| `_set_curados_false` | `_reset_curation_selection` |
| `tempFilesHarmonsile` | `tempFilesHarmonsmile` |

## Safe Migration Strategy

1. Add English aliases without removing the legacy names.
2. Keep all existing `state_keys.py` string values stable unless a deliberate
   Streamlit state migration is implemented.
3. Add tests that prove both legacy and new aliases resolve to the same
   behavior.
4. Update internal call sites gradually.
5. Remove legacy names only after the UI, services, tests, and any generated
   artifacts no longer depend on them.

## Current Decision

For the current refactor series, the legacy names are documented but preserved.
This avoids hidden changes to chemistry workflows, SQL behavior, Export,
HARMONSMILE, CHAMANP, session-state keys, and filesystem expectations.

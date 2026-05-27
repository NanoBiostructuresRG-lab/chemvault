from harmonsmile import PubChemIngest, PubChemConfig

cfg = PubChemConfig(
    input_path="examples/example_pubchem.csv",
    output_path="results/example_pubchem_harmonized.csv",
)
PubChemIngest(cfg).run()
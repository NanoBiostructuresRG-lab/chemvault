import json

with open("pubchem_protacxn_P34971_bioactivity_protein(2).json", "r", encoding="utf-8") as archivo:
    diccionario = json.load(archivo)

# Mostrar el contenido
print(diccionario)


CIDs= set()
AIDs= set()
for entry in diccionario:
    print(entry)
    CIDs.add(int(entry["cid"]))
    AIDs.add(int(entry["aid"]))

allCIDs = sorted(list(CIDs))
allAIDs = sorted(list(AIDs))


comparador_result = {
    "protein": "P34971",
    "total_unique_CIDs": len(allCIDs),
    "total_unique_AIDs": len(allAIDs),
    "CIDs": allCIDs,
    "AIDs": allAIDs
}

with open("comparador_result.json", "w", encoding="utf-8") as f:
    json.dump(comparador_result, f, indent=4)

print("Archivo guardado: comparador_result.json")

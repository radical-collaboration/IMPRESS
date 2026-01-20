import os
import re
import sys

# Define directories and files
#pdb_directory = '/WWW/out/'
#output_file = 'negative_ligand_filenames.txt'
#output_energy_file = 'negative_ligand_energies.txt'
#common_filenames_file = 'common_filenames.txt'

pdb_directory           = sys.argv[1]
output_file             = sys.argv[2]
output_energy_file      = sys.argv[3]
common_filenames_file   = sys.argv[4]
ligand_name             = sys.argv[5]

# Read common filenames
with open(common_filenames_file, 'r') as f:
    common_filenames = [line.strip() for line in f.readlines()]

# Create list of PDB files to analyze
pdb_files = [f for f in os.listdir(pdb_directory) if f.endswith('.pdb')]
files_to_analyze = []

for common_name in common_filenames:
    pattern = f"{common_name}.*.pdb"
    matching_files = [f for f in pdb_files if re.match(pattern, f)]
    files_to_analyze.extend(matching_files)

# Analyze the selected PDB files
for pdb_file in files_to_analyze:
    full_path = os.path.join(pdb_directory, pdb_file)
    
    # Initialize variables for ligand energy
    ligand_energy = None

    # Read the PDB file and find the ligand energy
    with open(full_path, 'r') as g:
        for line in g:
            if line.startswith(f"{ligand_name}"):
                # Extract the total energy value (last element)
                parts = line.split()
                ligand_energy = float(parts[-1])  # The last element is the total energy

                print(f"Processed: {pdb_file}, Ligand Energy ({ligand_name}): {ligand_energy}")
                
                # Check if the ligand energy is negative
                if ligand_energy < 0:
                    with open(output_file, 'a') as of:
                        of.write(f"{pdb_file}\n")
                    with open(output_energy_file, 'a') as oef:
                        oef.write(f"{pdb_file}\tLigand Energy: {ligand_energy}\n")
                break  # No need to check further lines

    if ligand_energy is None:
        print(f"File: {pdb_file} does not contain ligand {ligand_name}.")




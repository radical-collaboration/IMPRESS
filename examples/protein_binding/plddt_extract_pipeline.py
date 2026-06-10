import numpy as np
import os
import pandas as pd
import json
import argparse

# Peptide EGYQDYEPEA is 10 residues and always placed last in the Boltz FASTA
PEP_LEN = 10

parser = argparse.ArgumentParser()
parser.add_argument('--iter', type=str, help='pass iteration')
parser.add_argument('--out', type=str, help='pipeline name')
parser.add_argument('--path', type=str, help='base path')
args = parser.parse_args()

af_path = os.path.join(args.path, 'af_pipeline_outputs_multi', args.out, 'af/prediction')
dimer_models_path = os.path.join(af_path, 'dimer_models')

rows = []

for name in os.listdir(dimer_models_path):
    pred_dir = os.path.join(
        dimer_models_path, name, f"boltz_results_{name}", "predictions", name
    )
    plddt_file = os.path.join(pred_dir, f"plddt_{name}_model_0.npz")
    conf_file = os.path.join(pred_dir, f"confidence_{name}_model_0.json")
    pae_file = os.path.join(pred_dir, f"pae_{name}_model_0.npz")

    if not all(os.path.exists(f) for f in [plddt_file, conf_file, pae_file]):
        continue

    # avg_plddt: mean per-residue pLDDT (Boltz stores 0-1; scale to 0-100)
    plddt = np.load(plddt_file)['plddt']
    avg_plddt = float(plddt.mean() * 100)

    # iptm from Boltz confidence JSON — interface PTM is the primary binding quality metric
    with open(conf_file) as f:
        conf = json.load(f)
    iptm = conf.get('iptm', conf.get('ptm', 0.0))

    # avg_pae: mean cross-chain PAE between PDZ domain and peptide
    # Boltz outputs PDZ residues first, peptide last; PAE matrix is (N, N) in Angstroms
    pae_matrix = np.load(pae_file)['pae']
    total_res = pae_matrix.shape[0]
    pdz_len = total_res - PEP_LEN
    cross_pae = np.concatenate([
        pae_matrix[:pdz_len, pdz_len:].ravel(),
        pae_matrix[pdz_len:, :pdz_len].ravel(),
    ])
    avg_pae = float(cross_pae.mean()) if len(cross_pae) > 0 else 0.0

    rows.append({
        'ID': f"{name}.pdb",
        'avg_plddt': avg_plddt,
        'ptm': iptm,
        'avg_pae': avg_pae,
    })

print(f"Processed {len(rows)} structure(s)")

df = pd.DataFrame(rows, columns=['ID', 'avg_plddt', 'ptm', 'avg_pae'])
df.to_csv('af_stats_' + args.out + '_pass_' + args.iter + '.csv', index=False)

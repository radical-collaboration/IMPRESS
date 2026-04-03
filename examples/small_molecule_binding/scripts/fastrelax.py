import argparse
import joey_utils  as ut
from pyrosetta import init, Pose, PyJobDistributor
from pyrosetta.rosetta.core.select.residue_selector import (
	ResiduePropertySelector, NotResidueSelector
)
from pyrosetta.rosetta.core.chemical import ResidueProperty
'''
When downloading a new PDB file, relax with coordinate constraints to eliminate clashes.

Requires a PDB file input.

Options:
Name (-n, string): change the output PDB name from [original_name]_relaxed.pdb
Score function (-sf, string): change the score function from the default of ref2015_cst
Catalytic residues (-cat, int, multiple accepted): list residues that should not be moved 
'''

def parse_args():
	parser = argparse.ArgumentParser()
	parser.add_argument("pdb_file", help="What PDB file do you want to relax?")
	parser.add_argument("-od", "--out_dir", 
		help="Name an output directory for decoys (Default: current directory)")
	parser.add_argument('-name', "--name", 
		help="What do you want to name the relaxed PDB? (Default appends \
		'_relaxed' to original name.)")
	parser.add_argument("-suf", "--name_suffix", type=str,
		help="Add a suffix name to the output csv.")
	parser.add_argument('-n', "--n_decoys", type=int, default=100, 
		help="How many decoys do you want? (Default: 100)")
	parser.add_argument('-cst', "--constraints", default=None,
		help="If EnzDes constraints are to be applied in addition to the \
		default coordinate constraints, specify the file")
	parser.add_argument('-lig', "--ligand", default=None,
		help="If there is a ligand, specify the params file")
	parser.add_argument('-para', "--params", default=None,
		help="If there is extra params")
	parser.add_argument("-sug", "--sugars", action="store_true", 
		help="Include sugars/glycans in the model.")
	parser.add_argument('-sym', "--symmetry", default=None,
		help="If the relax should be symmetric, specify the symdef file")
	parser.add_argument('-cwt', "--constraint_weight", type=float, default=1.0,
		help="Specify the constraints weight for coordinates and enzdes \
		(Default: 1.0)")
	parser.add_argument("-nocons", "--no_constraints", action="store_true", 
		help="Option to not apply coordinate constraints to the pose when \
		relaxing.")
	parser.add_argument('-wat', '--waters', default=False, action='store_true',
    	help='Whether waters are present')
	args = parser.parse_args()
	return args


def main(args):
	# Determining file name
	if args.name: 
		out_name = ut.output_file_name(args.name, path=args.out_dir)
	else:
		out_name = ut.output_file_name(args.pdb_file, path=args.out_dir, 
			suffix='relaxed', extension=None)

	# Add name suffix
	if args.name_suffix:
		out_name = ut.output_file_name(out_name, suffix=args.name_suffix)

	# Loading pose and applying constraints, symmetry, 
	coord_cst = True
	if args.no_constraints:
		coord_cst = False
	pose = ut.load_pose(args.pdb_file, enzdes_cst=args.constraints, 
		coord_cst=coord_cst, symmetry=args.symmetry, membrane=None)

	# Setting up the scorefunction with the desired constraint weights
	sf = ut.get_sf(rep_type='hard', symmetry=args.symmetry, membrane=0, 
		constrain=args.constraint_weight)

	# Packer tasks with -ex1 and -ex2
	tf = ut.make_task_factory()

	# Creating FastRelax protocol with the given score function and task factory
	fr = ut.fast_relax_mover(sf, task_factory=tf)

	# RMSD metric
	rmsdm = ut.rmsd_metric(pose)

	# Ligand interaction energy selectors
	ligand_sel = ResiduePropertySelector(ResidueProperty.LIGAND)
	protein_sel = NotResidueSelector(ligand_sel)

	# Running relax set
	jd = PyJobDistributor(out_name, args.n_decoys, sf)
	while not jd.job_complete:
		pp = Pose(pose)
		fr.apply(pp)
		rmsdm.apply(pp)
		ut.interaction_energy(pp, sf, ligand_sel, protein_sel, apply_sm=True)
		jd.output_decoy(pp)


if __name__ == '__main__':
	args = parse_args()

	opts = '-ex1 -ex2 -use_input_sc -flip_HNQ -no_optH false -out:level 500'
	if args.constraints:
		opts += ' -enzdes::cstfile {}'.format(args.constraints)
		opts += ' -run:preserve_header'
	if args.ligand:
		opts += ' -extra_res_fa {}'.format(args.ligand)
		if args.params:
			opts += ' {}'.format(args.params)
	if args.sugars:
		opts += ' -include_sugars'
		opts += ' -auto_detect_glycan_connections'
		opts += ' -maintain_links '
		opts += ' -alternate_3_letter_codes rosetta/Rosetta/main/database/input_output/3-letter_codes/glycam.codes'
		opts += ' -write_glycan_pdb_codes'
		opts += ' -ignore_zero_occupancy false '
		opts += ' -load_PDB_components false'
		opts += ' -no_fconfig'
	if args.waters:
		opts += '  -ignore_waters false'
	init(opts)

	main(args)

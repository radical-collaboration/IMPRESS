import argparse
import joey_utils  as ut
from pyrosetta import init, Pose, PyJobDistributor
#Python
from pyrosetta import *
from pyrosetta.rosetta import *
from pyrosetta.teaching import *

#Core Includes
from rosetta.core.kinematics import MoveMap
from rosetta.core.kinematics import FoldTree
from rosetta.core.pack.task import TaskFactory
from rosetta.core.pack.task import operation
from rosetta.core.simple_metrics import metrics
from rosetta.core.select import residue_selector as selections
from rosetta.core import select
from rosetta.core.select.movemap import *

#Protocol Includes
from rosetta.protocols import minimization_packing as pack_min
from rosetta.protocols import relax as rel
from rosetta.protocols.antibody.residue_selector import CDRResidueSelector
from rosetta.protocols.antibody import *
from rosetta.protocols.loops import *
'''
When downloading a new PDB file, do a pack_min minimization with coordinate constraints and a ligand.

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
		help="What do you want to name the minimized PDB? (Default appends \
		'_minimized' to original name.)")
	parser.add_argument("-suf", "--name_suffix", type=str,
		help="Add a suffix name to the output csv.")
	parser.add_argument('-n', "--n_decoys", type=int, default=1, 
		help="How many decoys do you want? (Default: 1)")
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
			suffix='minimized', extension='pdb')

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
        #From pack_min tutorial from jupyter notebooks
        ###tf = TaskFactory()

	tf.push_back(operation.InitializeFromCommandline())
	tf.push_back(operation.RestrictToRepacking())
	packer = pack_min.PackRotamersMover()
	packer.task_factory(tf)

        #This line is from khare lab relax code, not sure if this will be necessary:
        #pp = Pose(pose)

        #Run the packer. (Note this may take a few minutes)
	packer.apply(pose)

        #Dump the PDB
	pose.dump_pdb(out_name)
        ##pose.dump_pdb('/outputs/2r0l_all_repack.pdb')

if __name__ == '__main__':
	args = parse_args()

	opts = '-ex1 -ex2 -use_input_sc -flip_HNQ -no_optH false'
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

#!/bin/sh
import argparse
parser = argparse.ArgumentParser()
import subprocess
#-db DATABSE -u USERNAME -p PASSWORD -size 20
parser.add_argument("-pdb", "--input_path", help="Input path", type=str)
parser.add_argument("-out", "--output_path", help="Output path", type=str)
parser.add_argument("-mpnn", "--mpnn_path", help="MPNN path", type=str)
parser.add_argument("-seqs", "--seqs", help="How many sequences designs would you like?", type=int)
parser.add_argument("-is_monomer", "--is_monomer", help="Is your input a monomer? (1 or 0)", type=int)
parser.add_argument("-chains", "--design_chains", help="Which input chains do you want designed? Separate with spaces. Example: -chains='A B'", type=str)
parser.add_argument("-index", "--index", help="Which specific indices do you want designed/fixed? Separate with spaces. For multiple chains, separate with comma. Example: -index='1 3 12, 2 7 14 56'", type=str)
parser.add_argument("-fix", "--fix", help="Would you like these positions fixed? (1 or 0)", type=int)
parser.add_argument("-tie", "--tie", help="Which specific indices across multiple chains do you want tied? Separate indices with spaces, chains with comma. Lists must be of same length. Example: -tie='1 2 3 4 5, 1 2 3 4 5'", type=str)
parser.add_argument("-homo", "--homo", help="Are your input files homomers? (0 or 1) Note: Overrides tied positions. If homomer is specified, all positions on designed chains will be tied. If positions are restricted, lists must be of same length. Example: -index='1 3 5 7, 1 3 5 7'", type=int)
parser.add_argument("-bias_AA", "--bias_AA", help="For which amino acids would you like to install bias? Example: -bias_AA='D E H'", type=str)
parser.add_argument("-bias_weight", "--bias_weight", help="What weights would you like to install for the biased amino acids? Lists must match in length. Example: -bias_weight='0.3 -0.3 0.5'", type=str)
parser.add_argument("-temp", "--temp", help="What temperature would you like to sample from? Example: 0.3", type=int, default=0.1)
parser.add_argument("-inter", "--interface", help="Would you like to design the interface? Do not specify indices if designing the interface. (1 or 0)", type=int, default=0)



args = parser.parse_args()

input_path=args.input_path
output_path=args.output_path
mpnn_path=args.mpnn_path
is_monomer=args.is_monomer #default is_monomer false
chains=args.design_chains
if chains == None:
	chains='A' #default design chain A
index=args.index
fix=args.fix #default false, specify non fixed
seqs=args.seqs
if seqs == None:
	seqs=1 #default 1 design per structure
tie=args.tie
homo=args.homo
interface=args.interface
temp=args.temp
bias_AA=args.bias_AA
bias_weight=args.bias_weight

if bias_weight!=None and bias_AA!=None:
	path_for_bias=output_path+"/bias_pdbs.jsonl"
	subprocess.call(['python', mpnn_path+"/helper_scripts/make_bias_AA.py", '--output_path='+path_for_bias, '--AA_list='+bias_AA, '--bias_list='+bias_weight])
else:
	path_for_bias=''


path_for_parsed_chains=output_path+"/parsed_pdbs.jsonl"

if is_monomer==True: #monomer - no need for interface or tie functionality
	subprocess.call(['python', mpnn_path+"/helper_scripts/parse_multiple_chains.py", '--input_path='+input_path, '--output_path='+path_for_parsed_chains])

	if index != None: #check if indices are specified
		path_for_assigned_chains=output_path+"/assigned_pdbs.jsonl"
		path_for_fixed_positions=output_path+"/fixed_pdbs.jsonl"
		subprocess.call(['python', mpnn_path+"/helper_scripts/assign_fixed_chains.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_assigned_chains, '--chain_list=A'])
		
		if fix==True: #check if indices are fixed or designed
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_fixed_positions_dict.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_fixed_positions, '--chain_list=A', '--position_list='+index])
		else:
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_fixed_positions_dict.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_fixed_positions, '--chain_list=A', '--position_list='+index, '--specify_non_fixed'])

		subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--bias_AA_jsonl='+path_for_bias])
		#monomeric, fixed
	else:
		subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--bias_AA_jsonl='+path_for_bias])
		#monomeric, unfixed

else: #multimer
	subprocess.call(['python', mpnn_path+"/helper_scripts/parse_multiple_chains.py", '--input_path='+input_path, '--output_path='+path_for_parsed_chains])
	path_for_assigned_chains=output_path+"/assigned_pdbs.jsonl"
	subprocess.call(['python', mpnn_path+"/helper_scripts/assign_fixed_chains.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_assigned_chains, '--chain_list='+chains])
	
	if index != None: #check if indices are specified
		
		path_for_fixed_positions=output_path+"/fixed_pdbs.jsonl"
		
		if fix==True: #check if indices are fixed or designed
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_fixed_positions_dict.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_fixed_positions, '--chain_list='+chains, '--position_list='+index])
		else:
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_fixed_positions_dict.py", '--input_path='+path_for_parsed_chains, '--output_path='+path_for_fixed_positions, '--chain_list='+chains, '--position_list='+index, '--specify_non_fixed'])
		
		if homo==True: #check for homomer
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--homooligomer=1'])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, fixed, homomer

		elif tie!=None: #check for tied positions
			
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--position_list='+tie])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, fixed, tied

		else:
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, fixed, untied
	
	elif interface==True:
		path_for_fixed_positions=output_path+"/interface_dict.jsonl"
		
		subprocess.call(['python', mpnn_path+"/helper_scripts/mk_interface_dict.py", '--input_path='+input_path, '--output_path='+path_for_fixed_positions])

		if homo==True: #check for homomer
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--homooligomer=1'])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, interface, homomer

		elif tie!=None: #check for tied positions
			
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--position_list='+tie])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, interface, tied

		else:
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--fixed_positions_jsonl='+path_for_fixed_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, interface, untied
	else:
		
		if homo==True: #check for homomer
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--homooligomer=1'])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, unfixed, homomer

		elif tie!=None: #check for tied positions
			
			path_for_tied_positions=output_path+"/tied_pdbs.jsonl"
			subprocess.call(['python', mpnn_path+"/helper_scripts/make_tied_positions_dict.py", '--input_path='+path_for_parsed_chains,'--output_path='+path_for_tied_positions, '--chain_list='+chains, '--position_list='+tie])
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--tied_positions_jsonl='+path_for_tied_positions, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, unfixed, tied

		else:
			subprocess.call(['python', mpnn_path+"/protein_mpnn_run.py", '--jsonl_path='+path_for_parsed_chains,'--out_folder='+output_path, '--num_seq_per_target='+str(seqs), '--sampling_temp='+str(temp), '--seed=37', '--batch_size=1', '--chain_id_jsonl='+path_for_assigned_chains, '--bias_AA_jsonl='+path_for_bias])
			#multimeric, unfixed, untied
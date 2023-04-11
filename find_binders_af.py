from pyrosetta import *
init()
from pyrosetta.rosetta.core.select.residue_selector import LayerSelector 
from pyrosetta.rosetta.protocols.scoring import Interface
from pyrosetta.teaching import *
import pandas as pd
DSSP = pyrosetta.rosetta.protocols.moves.DsspMover()
from joey_utils import hbond_selector
from joey_utils import index_selector
from pyrosetta.rosetta.core.select.residue_selector import ChainSelector
from pyrosetta.rosetta.utility import vector1_std_string
#from pyrosetta.toolbox import *
import os
file_list=[]
expected_status=[]
calculated_status=[]
agreement=[]
pgcn=[]
def find_sec_struct(struct_type, indices, pose, pep_or_pdz):
	#if pep_or_pdz == 'pep':
	struct_count=0
	ctr=0
	for residues in indices:
		if pose.secstruct(residues) == struct_type:
			struct_count+=1
			#print('$$$$$$$$$$$$$$$$$$$$$ length $$$$$$$$$$$$$$$$$$')
			#print(len(indices))
			#if ctr + 1 < len(indices):
			#	while pose.secstruct(indices[ctr+1]) == struct_type:
			#		struct_count+=1
			#		ctr+=1
			#		print('$$$$$$$$$$$$$$$$$$$$$ counter $$$$$$$$$$$$$$$$$$')
			#		print(ctr)
			#		if ctr + 1 >= len(indices):
			#			break
			#break
		ctr+=1
	if struct_count >= 1 and pep_or_pdz=='pep': # 2 strand residues on peptide
		return True, struct_count
	elif struct_count>=1 and pep_or_pdz=='pdz' and struct_type=='H': # 1 helical contact on pdz
		return True, struct_count
	elif struct_count>=1 and pep_or_pdz=='pdz' and struct_type=='E': # 2 strand contacts on pdz
		return True, struct_count
	else:
		return False, struct_count
	#elif pep_or_pdz == 'pdz':
		#struct_count=0
		#ctr=0
		#for residues in indices:
			#if pose.secstruct(residues) == struct_type:
				#struct_count+=1
				#print('$$$$$$$$$$$$$$$$$$$$$ length $$$$$$$$$$$$$$$$$$')
				#print(len(indices))
				#if ctr + 1 < len(indices):
				#	while pose.secstruct(indices[ctr+1]) == struct_type:
				#		struct_count+=1
				#		ctr+=1
						#print('$$$$$$$$$$$$$$$$$$$$$ counter $$$$$$$$$$$$$$$$$$')
						#print(ctr)
				#		if ctr + 1 >= len(indices):
				#			break
				#break
			#ctr+=1

		#if struct_count >= 2:
		#	return True, struct_count
		#else:
		#	return False, struct_count

def find_hbonds(pose):
	ch=ChainSelector()
	chain=vector1_std_string()
	chain.append('B')
	ch.set_chain_strings(chain)
	hh=hbond_selector(ch, False, True)
	bonders=hh.apply(pose)
	#indices=[]
	ctr=0
	for entries in bonders:
		if entries==1:
			#indices.append(ctr)
			ctr+=1
	return ctr

def find_cterm_hbonds(pose):
	index=len(pose.sequence())
	cterm=index_selector(index)
	#print("INDEX " + str(index))
	hh=hbond_selector(cterm, True, True)
	bonders=hh.apply(pose)
	#indices=[]
	ctr=0
	for entries in bonders:
		if entries==1:
			#indices.append(ctr)
			ctr+=1
	return ctr 

def new_metric(pose): #placeholder for PGCN
	return 1
#quick_list=[]

for files in os.listdir('af_pipeline_outputs/af/prediction/best_models/'):
	pose=pose_from_pdb('af_pipeline_outputs/af/prediction/best_models/'+files)
	DSSP.apply(pose)
	seq=pose.chain_sequence(1)
	length=len(seq)
	#ls = LayerSelector()
	#ls.set_layers(False, True, False)
	#boundary=ls.apply(pose)
	#counter=1
	#resi_list=[]
	#resi_list.append(files)
	#for entries in boundary:
	#	if entries==1:
	#		resi_list.append(counter)
	#	counter+=1
	#print(resi_list)
	scorefxn = get_fa_scorefxn()
	scorefxn.score(pose)
	dock_jump=1
	myinterface = Interface(dock_jump)
	myinterface.distance(5.0)
	myinterface.calculate(pose)
	#big_list.append(files)
	counter=0
	receptor_list=[]
	peptide_list=[]
	for entries in list(myinterface.pair_list()):
		for indices in entries:
			if indices > length:
				peptide_list.append(indices)
			else:
				receptor_list.append(indices)
			
	pdz_has_helix=False
	pdz_has_strand=False
	pep_has_strand=False
	is_bound_ss=0
	is_bound_hbond=0
	is_bound=0
	agrees=0
	#print(indices)
	pep_has_strand, pep_sec_length = find_sec_struct('E', peptide_list, pose, 'pep')
	if pep_has_strand == True:
		pdz_has_strand, pdz_strand_length = find_sec_struct('E', receptor_list, pose, 'pdz')
		pdz_has_helix , pdz_helix_length = find_sec_struct('H', receptor_list, pose, 'pdz')
		if pdz_has_strand == True and pdz_has_helix == True:
			is_bound_ss=1
			hbond_count=find_cterm_hbonds(pose)
			#print(files)
			#print(hbond_count)
			if hbond_count>=1:
				is_bound_hbond=1
	if is_bound_ss==1 and is_bound_hbond==1:
		is_bound=1

	#if files=='DFNB31_1_TNSRHGETTV_1_afd.pdb':
	#	quick_list.append(is_bound_ss)
	#	quick_list.append(is_bound_hbond)
	#	quick_list.append(is_bound)
	for x in os.listdir(output_path_mpnn+'job_'+str(passes)+'/seqs/'):
		if x.split('.')[0]==files.split('.')[0]:
			filepath=output_path_mpnn+'job_'+str(passes)+'/seqs/'+files
			file=open(filepath, 'r')
			lines=file.readlines()
			line_ctr=1
			for line in lines: #seq recovery
				if line_ctr==3:
					recovery_start=line.find('seq_recovery')
					recovery_start+=13
					percent=''
					#print(line[recovery_start])
					while line[recovery_start].isdigit()==True or line[recovery_start]=='.':
						percent+=line[recovery_start]
						recovery_start+=1
					break
				line_ctr+=1
	for models in os.listdir(output_path_af): #scores
		if models.split('.')[0]==files.split('.')[0]:
			pose=pose_from_pdb(output_path_af+models)
			pgcn_status=new_metric(pose)
			ch_a=chain_selector('A')
			ch_b=chain_selector('B')
			ch_a_bool=ch_a.apply(pose)
			ch_a_index=[]
			ctr=1
			for entries in ch_a_index:
				if entries==1:
					ch_a_index.append(ctr)
				ctr+=1
			mv=make_move_map(ch_a_index, True, False)
			fr=fast_relax_mover(movemap=mv)
			fr.apply(pose)
			#ch_a=chain_selector('A')
			#ch_b=chain_selector('B')
			interface=intergroup_selector(ch_a, ch_b)
			sfxn=get_fa_scorefxn()
			tf=make_task_factory(None, interface, None, None)
			pose=pack_mover(pose, sfxn, tf)
			energy=total_energy(pose, sfxn, interface)
			break
	
	file_list.append(files)
	calculated_status.append(is_bound)
	pgcn.append(pgcn_status)
	#print(receptor_list)	
	#counter+=1
	#print(counter)
#print(big_list)
big_list=tuple(zip(file_list, calculated_status, pgcn))
#big_list=tuple(zip(file_list, calculated_status))
#print(big_list)
df=pd.DataFrame(big_list, columns = ['ID','Calculated Status','PGCN'])
#print(df)	
df.to_csv('PDZ_bind_check_af.csv', index=False)
#print(quick_list)
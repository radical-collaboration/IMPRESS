from pyrosetta import *
init()
import subprocess
import os
from joey_utils import chain_selector
from joey_utils import intergroup_selector
from joey_utils import total_energy
from joey_utils import fast_relax_mover
from joey_utils import make_task_factory
from joey_utils import pack_mover
from joey_utils import make_move_map
import pandas as pd
input_path='benchmark_pipeline_input/'
output_path_mpnn='af_pipeline_outputs/mpnn/'
output_path_af='af_pipeline_outputs/af/prediction/best_models/'
my_dict={}
for i in range(1,6): #set up mpnn directories if needed
	if os.path.exists(output_path_mpnn+"job_"+str(i))==False:
		os.mkdir(output_path_mpnn+"job_"+str(i))

for files in os.listdir("benchmark_struct/"): #initial scores
	pose=pose_from_pdb("benchmark_struct/"+files)
	ch_a=chain_selector('A')
	ch_b=chain_selector('B')
	interface=intergroup_selector(ch_a, ch_b)
	sfxn=get_fa_scorefxn()
	energy=total_energy(pose, sfxn, interface)
	my_dict[files.split('.')[0]]=[str(energy)]

subprocess.call(['python', 'mpnn_wrapper.py', '-pdb='+input_path, '-out='+output_path_mpnn+'job_1/', '-mpnn=../../ProteinMPNN/', '-seqs=1', '-is_monomer=0', '-chains=A']) #initial mpnn run
print("INITIAL MPNN COMPLETE")
#extract sequence recovery, put in list
#---------------------------------------
#percent_list=[]
#file_list=[]
#pass_list=[]
	#percent_list.append(percent)
	#file_list.append(files)
	#pass_list.append(1)

#---------------------------------------
subprocess.call(['python', 'af_check.py', '-pdb='+input_path, '-out='+output_path_mpnn+'job_1/seqs/']) #make fasta files from mpnn output
#5 passes
passes=1
while passes<=4:
	subprocess.call('./jon_job.sh') #run af2-multi on fasta file made from mpnn design, should wait until af jobs are finished
	print("ALPHAFOLD PASS "+str(passes)+" COMPLETE")
	subprocess.call(['python', 'find_binders_af.py']) #determine if peptides in af structures are bound or not, store in PDZ_bind_check.csv
	df=pd.read_csv('PDZ_bind_check_af.csv')
	names=df['ID']
	status=df['Calculated Status']
	pgcn=df['PGCN']

	#extract sequence recovery, scores, and bound status, put in list
	#----------------------
	for files in os.listdir(output_path_mpnn+'job_'+str(passes)+'/seqs/'):
		for keys, values in my_dict.items():
			if keys==files.split('.')[0]:
				for x, y, z in zip(names, status, pgcn):
					if x==files.split('.')[0]:
						temp_status=y
						temp_pgcn=z
				my_dict[keys].append(str(temp_status)+"_"+str(temp_pgcn))
				break

		#percent_list.append(percent)
		#file_list.append(files)
		#pass_list.append(passes)
	#-----------------------
	
	passes+=1 #update for next pass
	subprocess.call(['python', 'mpnn_wrapper.py', '-pdb='+output_path_af, '-out='+output_path_mpnn+'job_'+str(passes)+'/', '-mpnn=../../ProteinMPNN/', '-seqs=1', '-is_monomer=0', '-chains=A']) #run mpnn on af2 strucutres
	print("MPNN PASS "+str(passes)+" COMPLETE")
	subprocess.call(['python', 'af_check.py', '-pdb='+input_path, '-out='+output_path_mpnn+'job_'+str(passes)+'/seqs/']) #make fasta files from mpnn output

subprocess.call('./jon_job.sh') #run af2-multi on fasta file made from mpnn design, should wait until af jobs are finished
print("ALPHAFOLD PASS "+str(passes)+" COMPLETE")
subprocess.call(['python', 'find_binders_af.py']) #determine if peptides in af structures are bound or not, store in PDZ_bind_check.csv
df=pd.read_csv('PDZ_bind_check_af.csv')
names=df['ID']
status=df['Calculated Status']
pgcn=df['PGCN']
#extract sequence recovery, scores, and bound status, put in list
#----------------------
for files in os.listdir(output_path_mpnn+'job_'+str(passes)+'/seqs/'):
	for keys, values in my_dict.items():
		if keys==files.split('.')[0]:
			for x, y, z in zip(names, status, pgcn):
				if x==files.split('.')[0]:
					temp_status=y
					temp_pgcn=z
			my_dict[keys].append(str(temp_status)+"_"+str(temp_pgcn))
			break
print(my_dict)
#RANKING BY SEQ RECOVERY
#-------------------------------------
#file_list=[]
#max_percent_list=[]
#max_pass_list=[]
#for keys, values in my_dict.items():
#	temp_list=values
#	percent_list=[i.split('_')[0] for i in temp_list]
#	pass_list=[j.split('_')[1] for j in temp_list]
#	percent_list=list(map(float, percent_list))
#	temp_max=max(percent_list)
#	max_index=percent_list.index(temp_max)
#	temp_pass=pass_list[max_index]
#	file_list.append(keys)
#	max_percent_list.append(temp_max)
#	max_pass_list.append(temp_pass)
#final=list(zip(file_list, max_percent_list, max_pass_list))
#print(final)
#--------------------------------------
#RANKING BY INTERFACE ENERGY
#--------------------------------------

with open('af_pipeline_output_summary.jsonl','w') as f:
	f.write(str(my_dict))
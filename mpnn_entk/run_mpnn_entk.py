#!/usr/bin/env python

import os
import pandas as pd

from pyrosetta import *
init()
from joey_utils import pack_mover
from joey_utils import total_energy
from joey_utils import make_move_map
from joey_utils import chain_selector
from joey_utils import fast_relax_mover
from joey_utils import make_task_factory
from joey_utils import intergroup_selector

from radical.entk import Pipeline, Stage, Task, AppManager
import sys
# ------------------------------------------------------------------------------
# Set default verbosity
if os.environ.get('RADICAL_ENTK_VERBOSE') is None:
    os.environ['RADICAL_ENTK_REPORT'] = 'True'
full_path='/home/ja961/Khare/pipeline/'

input_path=full_path+'test_pipeline_input/'
output_path_mpnn=full_path+'af_pipeline_outputs/mpnn/'
output_path_af=full_path+'af_pipeline_outputs/af/prediction/best_models/'
my_dict={}

# Set up mpnn directories if needed
for i in range(1,6): 
    if os.path.exists(output_path_mpnn+"job_"+str(i))==False:
        os.mkdir(output_path_mpnn+"job_"+str(i))

fasta_list=[]
# Initial scores
for files in os.listdir("test_pipeline_input/"): 
    pose=pose_from_pdb("test_pipeline_input/"+files)
    ch_a=chain_selector('A')
    ch_b=chain_selector('B')
    interface=intergroup_selector(ch_a, ch_b)
    sfxn=get_fa_scorefxn()
    energy=total_energy(pose, sfxn, interface)
    my_dict[files.split('.')[0]]=[str(energy)]
    fasta_list.append(files.split('.')[0]+'.fa')



# Create a Pipeline object
mpnn_pipeline = Pipeline()
# Create a Stage object
s1 = Stage()
s1.name = 'Stage.1.mpnn.wrapper'

# Create a Task object
t1 = Task()
t1.name = 'T1.initial.mpnn.run'
t1.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh','conda activate pyr']
t1.executable = 'python' 
t1.arguments = [full_path+'mpnn_wrapper.py',
                '-pdb='+input_path,
                '-out='+output_path_mpnn+'job_1/',
                '-mpnn='+full_path+'../../ProteinMPNN/', '-seqs=1',
                '-is_monomer=0', '-chains=A']

s1.add_tasks(t1)

# Create a Stage object
s2 = Stage()
s2.name = 'Stage.2.af.check'

# Create a Task object
t2 = Task()
t2.name = 'T2.make.fasta'
t2.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh', 'conda activate pyr']
t2.executable = 'python' 
t2.arguments = [full_path+'/af_check.py',
                '-pdb='+input_path,
                '-out='+output_path_mpnn+'job_1/seqs/']

s2.add_tasks(t2)

mpnn_pipeline.add_stages([s1, s2])
passes=2

file_list=[]
#for i in range(passes_max):
while passes <= 4:
	# Create a Stage object
	#passes=i+2
	#python slurmit_BAY.py --job $jobname --partition gpu --tasks 8 --cpus 1 --mem 32G --time 4:00:00 --begin now --requeue True --outfiles $od/prediction/logs/${jobname}_%a --command "$com"
	print(passes)
	s3 = Stage()
	s3.name = 'Stage.3.af2.multi.{0}'.format(passes)
	os.environ['passes']=str(passes)
	for fastas in fasta_list:
		t3 = Task()
		t3.name = 'T3.af2.passes.'+fastas.split('.')[0].replace('_','')+'{0}'.format(passes)
		t3.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','echo $passes >> debug.txt']
		t3.executable = '/bin/bash'
		t3.arguments = [full_path+'af2_multimer_reduced.sh',full_path+'af_pipeline_outputs/af/fasta/'+fastas,full_path+'af_pipeline_outputs/af/prediction/dimer_models/']
		t3.post_exec = ['cp ' +full_path+ 'af_pipeline_outputs/af/prediction/dimer_models/'+fastas.split('.')[-2]+'/*ranked_0*.pdb '+full_path+'af_pipeline_outputs/af/prediction/best_models/'+fastas.split('.')[-2]+'.pdb']
		t3.cpu_reqs = {'cpu_processes':1}
		t3.gpu_reqs = {'gpu_processes':1}
		# t3.executable = 'python'
		# t3.arguments = [full_path+'dummy_job.py','-passes='+str(passes)]
		s3.add_tasks(t3)
	#sys.exit(0)

	# Create a Stage object
	s4 = Stage()
	s4.name = 'Stage.4.peptides.{0}'.format(passes)

	t4 = Task()
	t4.name = 'T4.peptides.passes.{0}'.format(passes)
	t4.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh', 'conda activate pyr']
	t4.executable = 'python'
	t4.arguments = [full_path+'find_binders_af.py','-iter='+str(passes)]
	t4.download_output_data = ['PDZ_bind_check_af_'+str(passes)+'.csv']

	s4.add_tasks(t4)
	file_list.append('PDZ_bind_check_af_'+str(passes)+'.csv')
	# Download the output of the current task to the current location


	# Create a Stage object
	s5 = Stage()
	s5.name = 'Stage.5.af2structure.{0}'.format(passes)

	t5 = Task()
	t5.name = 'T5.run.mpnn.passes.{0}'.format(passes)
	t5.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh', 'conda activate pyr']
	t5.executable = 'python'
	t5.arguments = [full_path+'mpnn_wrapper.py',
	                '-pdb='+output_path_af,
	                '-out='+output_path_mpnn+'job_'+str(passes)+'/',
	                '-mpnn='+full_path+'../../ProteinMPNN/', '-seqs=1', '-is_monomer=0', '-chains=B']
	s5.add_tasks(t5)

	# Create a Stage object
	s6 = Stage()
	s6.name = 'Stage.6.af2structure.{0}'.format(passes)

	t6 = Task()
	t6.name = 'T6.run.mpnn.passes.{0}'.format(passes)
	t6.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh', 'conda activate pyr']
	t6.executable = 'python'
	t6.arguments = [full_path+'af_check.py',
	                '-pdb='+input_path,
	                '-out='+output_path_mpnn+'job_'+str(passes)+'/seqs/']

	s6.add_tasks(t6)
    # Add Stage to the Pipeline
	mpnn_pipeline.add_stages([s3, s4, s5, s6])
	passes+=1
# Create a Stage object
s7 = Stage()
s7.name = 'Stage.7.jon.job'
print(file_list)

for fastas in fasta_list:
    t7 = Task()
    t7.name = 'T7.af2.passes.'+fastas.split('.')[0].replace('_','')+'{0}'.format(passes)
    t7.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile']
    t7.executable = '/bin/bash'
    t7.arguments = [full_path+'af2_multimer_reduced.sh',full_path+'af_pipeline_outputs/af/fasta/'+fastas,full_path+'af_pipeline_outputs/af/prediction/dimer_models/']
    t7.post_exec = ['cp ' +full_path+ 'af_pipeline_outputs/af/prediction/dimer_models/'+fastas.split('.')[-2]+'/*ranked_0*.pdb '+full_path+'af_pipeline_outputs/af/prediction/best_models/'+fastas.split('.')[-2]+'.pdb']
    t7.cpu_reqs = {'cpu_processes':1}
    t7.gpu_reqs = {'gpu_processes':1}
    s7.add_tasks(t7)
# Create a Stage object
s8 = Stage()
s8.name = 'Stage.8.find.binders'

t8 = Task()
t8.name = 'T8.find.binders'
t8.pre_exec = ['. /opt/sw/admin/lmod/lmod/init/profile','source /home/ja961/anaconda3/etc/profile.d/conda.sh', 'conda activate pyr']
t8.executable = 'python'
t8.arguments = [full_path+'find_binders_af.py','-iter='+str(passes)]
t8.download_output_data = ['PDZ_bind_check_af_'+str(passes)+'.csv']
file_list.append('PDZ_bind_check_af_'+str(passes)+'.csv')
s8.add_tasks(t8)

mpnn_pipeline.add_stages([s7, s8])

# Create Application Manager
appman = AppManager()

# Assign the workflow as a set or list of Pipelines to the Application Manager
appman.workflow = set([mpnn_pipeline])

# Create a dictionary describe four mandatory keys:
# resource, walltime, cpus and project
# resource is 'local.localhost' to execute locally
res_dict = {'resource': 'rutgers.amarel',
            'access_schema': 'interactive',
            'walltime': 4320,
            'cpus': 8,
            'gpus': 8,
	   }
# Assign resource request description to the Application Manager
appman.resource_desc = res_dict

# Run the Application Manager
appman.run()


for a in file_list:
	df = pd.read_csv(a)
	names=df['ID']
	status=df['Calculated Status']
	pgcn=df['PGCN']
	cur_round=df['Round']
	# Extract sequence recovery, scores, and bound status, put in list
	for files in fasta_list:
		print('FILE: '+files)
		for keys, values in my_dict.items():
			if keys==files.split('.')[0]:
				print('KEY: '+keys)
				for x, y, z, w in zip(names, status, pgcn, cur_round):
					if x.split('.')[0]==files.split('.')[0]:
						print('APPEND')
						temp_status=y
						temp_pgcn=z
						temp_round=w
						my_dict[keys].append('plddt: '+str(temp_status)+" peptide contacts: "+str(temp_pgcn)+ ' round: '+str(w))
						break

print(my_dict)

with open('af_pipeline_output_summary.jsonl','w') as f:
    f.write(str(my_dict))

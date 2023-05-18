#!/usr/bin/env python

import os
import pandas as pd

from pyrosetta import *
from joey_utils import pack_mover
from joey_utils import total_energy
from joey_utils import make_move_map
from joey_utils import chain_selector
from joey_utils import fast_relax_mover
from joey_utils import make_task_factory
from joey_utils import intergroup_selector

from radical.entk import Pipeline, Stage, Task, AppManager

# ------------------------------------------------------------------------------
# Set default verbosity
if os.environ.get('RADICAL_ENTK_VERBOSE') is None:
    os.environ['RADICAL_ENTK_REPORT'] = 'True'


PASSES=1

input_path='benchmark_pipeline_input/'
output_path_mpnn='af_pipeline_outputs/mpnn/'
output_path_af='af_pipeline_outputs/af/prediction/best_models/'
my_dict={}

# Set up mpnn directories if needed
for i in range(1,6): 
    if os.path.exists(output_path_mpnn+"job_"+str(i))==False:
		os.mkdir(output_path_mpnn+"job_"+str(i))

# Initial scores
for files in os.listdir("benchmark_struct/"): 
    pose=pose_from_pdb("benchmark_struct/"+files)
    ch_a=chain_selector('A')
    ch_b=chain_selector('B')
    interface=intergroup_selector(ch_a, ch_b)
    sfxn=get_fa_scorefxn()
    energy=total_energy(pose, sfxn, interface)
    my_dict[files.split('.')[0]]=[str(energy)]


# Create a Pipeline object
mpnn_pipeline = Pipeline()

# Create a Stage object
s1 = Stage()
s1.name = 'Stage.1.mpnn_wrapper'

# Create a Task object
t1 = Task()
t1.name = 'T1.initial.mpnn_run'
t1.pre_exec = ['source $HOME/mpnn_env/bin/activate']
t1.executable = 'python' 
t1.arguments = ['mpnn_wrapper.py',
                '-pdb='+input_path,
                '-out='+output_path_mpnn+'job_1/',
                '-mpnn=../../ProteinMPNN/', '-seqs=1',
                '-is_monomer=0', '-chains=A']

s1.add_tasks(t1)

# Create a Stage object
s2 = Stage()
s2.name = 'Stage.2.af_check'

# Create a Task object
t2 = Task()
t2.name = 'T2.make.fasta'
t2.pre_exec = ['source $HOME/mpnn_env/bin/activate']
t2.executable = 'python' 
t2.arguments = ['af_check.py',
                '-pdb='+input_path,
                '-out='+output_path_mpnn+'job_1/seqs/']

s2.add_tasks(t2)

mpnn_pipeline.add_stages([s1, s2])

while PASSES <= 4:
    # Create a Stage object
    s3 = Stage()
    s3.name = 'Stage.3.af2-multi.{0}'.format(PASSES)

    t3 = Task()
    t3.name = 'T3.af2.passes.{0}'.format(PASSES)
    t3.executable = '/bin/bash'
    t3.arguments = ['$HOME/jon_job.sh']

    s3.add_tasks(t3)

    # Create a Stage object
    s4 = Stage()
    s4.name = 'Stage.4.peptides.{0}'.format(PASSES)

    t4 = Task()
    t4.name = 'T4.peptides.passes.{0}'.format(PASSES)
    t4.pre_exec = ['source $HOME/mpnn_env/bin/activate']
    t4.executable = 'python'
    t4.arguments = ['find_binders_af.py']

    s4.add_tasks(t4)

    # Download the output of the current task to the current location
    t4.download_output_data = ['PDZ_bind_check_af.csv']

    # Should we make this as a function task?
    df = pd.read_csv('PDZ_bind_check_af.csv')
    names=df['ID']
    status=df['Calculated Status']
    pgcn=df['PGCN']

    # Extract sequence recovery, scores, and bound status, put in list
    for files in os.listdir(output_path_mpnn+'job_'+str(PASSES)+'/seqs/'):
        for keys, values in my_dict.items():
            if keys==files.split('.')[0]:
                for x, y, z in zip(names, status, pgcn):
                    if x==files.split('.')[0]:
                        temp_status=y
                        temp_pgcn=z
                my_dict[keys].append(str(temp_status)+"_"+str(temp_pgcn))
                break

    # Create a Stage object
    s5 = Stage()
    s5.name = 'Stage.5.af2structure.{0}'.format(PASSES)

    t5 = Task()
    t5.name = 'T5.run.mpnn.passes.{0}'.format(PASSES)
    t5.pre_exec = ['source $HOME/mpnn_env/bin/activate']
    t5.executable = 'python'
    t5.arguments = ['mpnn_wrapper.py',
                    '-pdb='+output_path_af,
                    '-out='+output_path_mpnn+'job_'+str(PASSES)+'/',
                    '-mpnn=../../ProteinMPNN/', '-seqs=1', '-is_monomer=0', '-chains=A']
    s5.add_tasks(t5)

    # Create a Stage object
    s6 = Stage()
    s6.name = 'Stage.6.af2structure.{0}'.format(passPASSESes)

    t6 = Task()
    t6.name = 'T6.run.mpnn.passes.{0}'.format(PASSES)
    t6.pre_exec = ['source $HOME/mpnn_env/bin/activate']
    t6.executable = 'python'
    t6.arguments = ['af_check.py',
                    '-pdb='+input_path,
                    '-out='+output_path_mpnn+'job_'+str(PASSES)+'/seqs/']

    s6.add_tasks(t6)

    # Add Stage to the Pipeline
    mpnn_pipeline.add_stages([s3, s4, s5, s6])
    PASSES+=1

# Create a Stage object
s7 = Stage()
s7.name = 'Stage.7.jon_job'

t7 = Task()
t7.name = 'T7.jon_job'
t7.pre_exec = ['source $HOME/mpnn_env/bin/activate']
t7.executable = '/bin/bash'
t7.arguments = ['$HOME/jon_job.sh']

s7.add_tasks(t7)

# Create a Stage object
s8 = Stage()
s8.name = 'Stage.8.find_binders'

t8 = Task()
t8.name = 'T8.find_binders'
t8.pre_exec = ['source $HOME/mpnn_env/bin/activate']
t8.executable = 'python'
t8.arguments = ['find_binders_af.py']

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
            'walltime': 60,
            'cpus': 24,
            'gpus': 0
	   }
# Assign resource request description to the Application Manager
appman.resource_desc = res_dict

# Run the Application Manager
appman.run()

df=pd.read_csv('PDZ_bind_check_af.csv')
names=df['ID']
status=df['Calculated Status']
pgcn=df['PGCN']

# Extract sequence recovery, scores, and bound status, put in list
for files in os.listdir(output_path_mpnn+'job_'+str(PASSES)+'/seqs/'):
    for keys, values in my_dict.items():
        if keys==files.split('.')[0]:
            for x, y, z in zip(names, status, pgcn):
                if x==files.split('.')[0]:
                    temp_status=y
                    temp_pgcn=z
            my_dict[keys].append(str(temp_status)+"_"+str(temp_pgcn))
            break

print(my_dict)

with open('af_pipeline_output_summary.jsonl','w') as f:
    f.write(str(my_dict))

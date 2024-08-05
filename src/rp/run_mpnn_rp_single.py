#!/usr/bin/env python

import os
import pandas as pd

from pyrosetta import *
init()

from joey_utils import (
	pack_mover, total_energy, make_move_map, chain_selector, fast_relax_mover,
	make_task_factory, intergroup_selector)

import radical.pilot as rp
import radical.utils as ru

BASE_PATH = '/home/ja961/Khare/pipeline'  # full path
all_files = []


def run_pipeline(pipe_name, tmgr):
    global all_files

    input_path = f'{BASE_PATH}/{pipe_name}_in'
    output_path_mpnn = f'{BASE_PATH}/af_pipeline_outputs_multi/{pipe_name}/mpnn'
    output_path_af = f'{BASE_PATH}/af_pipeline_outputs_multi/{pipe_name}/' + \
                     'af/prediction/best_models'

    # Set up mpnn directories if needed
    for i in range(1, 6):
        job_dir = f'{output_path_mpnn}/job_{i}'
        if not os.path.exists(job_dir):
            os.mkdir(job_dir)

    fasta_list_2 = []
    for files in os.listdir(f'{pipe_name}_in'):
        fasta_list_2.append(files)
    print('$$$')
    print(fasta_list_2)
    print('$$$')
    # Initial scores
    # my_dict = {}
    # for files in os.listdir("test_pipeline_input_"+pipe_name+"/"):
    #     pose=pose_from_pdb("test_pipeline_input_"+pipe_name+"/"+files)
    #     ch_a=chain_selector('A')
    #     ch_b=chain_selector('B')
    #     interface=intergroup_selector(ch_a, ch_b)
    #     sfxn=get_fa_scorefxn()
    #     energy=total_energy(pose, sfxn, interface)
    #     my_dict[files.split('.')[0]]=[str(energy)]
    #     fasta_list.append(files.split('.')[0]+'.fa')

    print('Stage.1.mpnn.wrapper')
    tds = []
    tds.append(rp.TaskDescription({
        'uid': ru.generate_id('t1.%(item_counter)06d',
                              ru.ID_CUSTOM, ns=tmgr.session.uid),
        'name': 'T1.initial.mpnn.run',
        'executable': 'python',
        'arguments': [f'{BASE_PATH}/mpnn_wrapper.py',
                      f'-pdb={input_path}/',
                      f'-out={output_path_mpnn}/job_1/',
                      f'-mpnn={BASE_PATH}/../../ProteinMPNN/',
                      '-seqs=1',
                      '-is_monomer=0',
                      '-chains=A'],
        'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                     'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                     'conda activate pyr']
    }))
    tasks = tmgr.submit_tasks(tds)
    tmgr.wait_tasks(uids=[t.uid for t in tasks])

    print('Stage.2.af.check')
    tds = []
    tds.append(rp.TaskDescription({
        'uid': ru.generate_id('t2.%(item_counter)06d',
                              ru.ID_CUSTOM, ns=tmgr.session.uid),
        'name': 'T2.make.fasta',
        'executable': 'python',
        'arguments': [f'{BASE_PATH}/af_check.py',
                      f'-pdb={input_path}/',
                      f'-out={output_path_mpnn}/job_1/seqs/',
                      f'-write_path={pipe_name}/'],
        'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                     'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                     'conda activate pyr']
    }))
    tasks = tmgr.submit_tasks(tds)
    tmgr.wait_tasks(uids=[t.uid for t in tasks])

    passes = 2
    while passes <= 4:

        print(f'Stage.3.af2.multi.{passes}')
        tds = []
        os.environ['passes'] = str(passes)
        for fastas in fasta_list_2:
            name_k = fastas.split('.')[0].replace('_', '')
            tds.append(rp.TaskDescription({
                'uid': ru.generate_id('t3.%(item_counter)06d',
                                      ru.ID_CUSTOM, ns=tmgr.session.uid),
                'name': f'T3.af2.passes.{name_k}{passes}',
                'executable': '/bin/bash',
                'arguments': [f'{BASE_PATH}/af2_multimer_reduced.sh',
                              f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                              f'{pipe_name}/af/fasta/{fastas.split(".")[0]}.fa',
                              f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                              f'{pipe_name}/af/prediction/dimer_models/'],
                'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                             'echo $passes >> debug.txt'],
                'post_exec': [f'cp {BASE_PATH}/af_pipeline_outputs_multi/' +
                              f'{pipe_name}/af/prediction/dimer_models/' +
                              f'{fastas.split(".")[-2]}/*ranked_0*.pdb ' +
                              f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                              f'{pipe_name}/af/prediction/best_models/' +
                              f'{fastas.split(".")[-2]}.pdb'],
                'gpus_per_rank': 1
            }))
        tasks = tmgr.submit_tasks(tds)
        tmgr.wait_tasks(uids=[t.uid for t in tasks])

        print(f'Stage.4.peptides.{passes}')
        staged_file = f'PDZ_bind_check_af_{passes}_{pipe_name}.csv'
        all_files.append(staged_file)
        tds = []
        tds.append(rp.TaskDescription({
            'uid': ru.generate_id('t4.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=tmgr.session.uid),
            'name': f'T4.peptides.passes.{passes}',
            'executable': 'python',
            'arguments': [f'{BASE_PATH}/find_binders_af.py',
                          f'-iter={passes}',
                          f'-dir={pipe_name}'],
            'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                         'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                         'conda activate pyr'],
            # download the output of the current task to the current location
            'output_staging': [{'source': f'task:///{staged_file}',
                                'target': f'client:///{staged_file}'}]
        }))
        tasks = tmgr.submit_tasks(tds)
        tmgr.wait_tasks(uids=[t.uid for t in tasks])

        print(f'Stage.5.af2structure.{passes}')
        tds = []
        tds.append(rp.TaskDescription({
            'uid': ru.generate_id('t5.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=tmgr.session.uid),
            'name': f'T5.run.mpnn.passes.{passes}',
            'executable': 'python',
            'arguments': [f'{BASE_PATH}/mpnn_wrapper.py',
                          f'-pdb={output_path_af}/',
                          f'-out={output_path_mpnn}/job_{passes}/',
                          f'-mpnn={BASE_PATH}/../../ProteinMPNN/',
                          '-seqs=1',
                          '-is_monomer=0',
                          '-chains=B'],
            'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                         'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                         'conda activate pyr']
        }))
        tasks = tmgr.submit_tasks(tds)
        tmgr.wait_tasks(uids=[t.uid for t in tasks])

        print(f'Stage.6.af2structure.{passes}')
        tds = []
        tds.append(rp.TaskDescription({
            'uid': ru.generate_id('t6.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=tmgr.session.uid),
            'name': f'T6.run.mpnn.passes.{passes}',
            'executable': 'python',
            'arguments': [f'{BASE_PATH}/af_check.py',
                          f'-pdb={input_path}/',
                          f'-out={output_path_mpnn}/job_{passes}/seqs/',
                          f'-write_path={pipe_name}/'],
            'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                         'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                         'conda activate pyr']
        }))
        tasks = tmgr.submit_tasks(tds)
        tmgr.wait_tasks(uids=[t.uid for t in tasks])

        passes += 1

    print('Stage.7.jon.job')
    print(all_files)
    tds = []
    for fastas in fasta_list_2:
        name_k = fastas.split('.')[0].replace('_', '')
        tds.append(rp.TaskDescription({
            'uid': ru.generate_id('t7.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=tmgr.session.uid),
            'name': f'T7.af2.passes.{name_k}{passes}',
            'executable': '/bin/bash',
            'arguments': [f'{BASE_PATH}/af2_multimer_reduced.sh',
                          f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                          f'{pipe_name}/af/fasta/{fastas.split(".")[0]}.fa',
                          f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                          f'{pipe_name}/af/prediction/dimer_models/'],
            'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile'],
            'post_exec': [f'cp {BASE_PATH}/af_pipeline_outputs_multi/' +
                          f'{pipe_name}/af/prediction/dimer_models/' +
                          f'{fastas.split(".")[-2]}/*ranked_0*.pdb ' +
                          f'{BASE_PATH}/af_pipeline_outputs_multi/' +
                          f'{pipe_name}/af/prediction/best_models/' +
                          f'{fastas.split(".")[-2]}.pdb'],
            'gpus_per_rank': 1
        }))
    tasks = tmgr.submit_tasks(tds)
    tmgr.wait_tasks(uids=[t.uid for t in tasks])

    print('Stage.8.find.binders')
    staged_file = f'PDZ_bind_check_af_{passes}_{pipe_name}.csv'
    all_files.append(staged_file)
    task = tmgr.submit_tasks(rp.TaskDescription({
        'uid': ru.generate_id('t8.%(item_counter)06d',
                              ru.ID_CUSTOM, ns=tmgr.session.uid),
        'name': 'T8.find.binders',
        'executable': 'python',
        'arguments': [f'{BASE_PATH}/find_binders_af.py',
                      f'-iter={passes}',
                      f'-dir={pipe_name}'],
        'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                     'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                     'conda activate pyr'],
        'post_exec': [],
        'output_staging': [{'source': f'task:///{staged_file}',
                            'target': f'client:///{staged_file}'}]
    }))
    tmgr.wait_tasks(uids=[task.uid])


pipe_list = ['p1'] #, 'p2']
my_dict = {}
for i in pipe_list:
    for files in os.listdir(i + '_in/'):
        my_dict[files.split('.')[0]] = []
fasta_list = []
for a in my_dict.keys():
    fasta_list.append(a)


session = rp.Session()
pmgr = rp.PilotManager(session)
tmgr = rp.TaskManager(session)

pilot = pmgr.submit_pilots(rp.PilotDescription({
    'resource'     : 'rutgers.amarel',
    'runtime'      : 4320,
    'cores'        : 4,
    'gpus'         : 4
}))

tmgr.add_pilots(pilot)
pilot.wait(rp.PMGR_ACTIVE)

run_pipeline('p1', tmgr)

session.close(download=True)

for a in all_files:
    df = pd.read_csv(a)
    names = df['ID']
    status = df['Calculated Status']
    pgcn = df['PGCN']
    cur_round = df['Round']
    # Extract sequence recovery, scores, and bound status, put in list
    for files in fasta_list:
        print('FILE: ' + files)
        for keys, values in my_dict.items():
            if keys == files.split('.')[0]:
                print('KEY: ' + keys)
                for x, y, z, w in zip(names, status, pgcn, cur_round):
                    if x.split('.')[0] == files.split('.')[0]:
                        print('APPEND')
                        temp_status = y
                        temp_pgcn = z
                        temp_round = w
                        my_dict[keys].append('plddt: ' + str(
                            temp_status) + " peptide contacts: " + str(
                            temp_pgcn) + ' round: ' + str(w))
                        break

print(my_dict)

with open('af_pipeline_output_summary.jsonl', 'w') as f:
    f.write(str(my_dict))


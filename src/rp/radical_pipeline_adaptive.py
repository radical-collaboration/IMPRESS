#!/usr/bin/env python

import os
import pandas as pd
import queue
import shutil
from collections import defaultdict

from pyrosetta import *
init()

import radical.pilot as rp
import radical.utils as ru

BASE_PATH = '/home/ja961/Khare/pipeline'
PIPELINE_NAMES = ['p1', 'p2']
TASK_PRE_EXEC  = ['. /opt/sw/admin/lmod/lmod/init/profile',
                  'source /home/ja961/anaconda3/etc/profile.d/conda.sh',
                  'conda activate pyr']

tasks_finished_queue = queue.Queue()
new_pipelines_queue  = queue.Queue()
# change set up dirs to read from config file for all paths, also requested resources + pilot description
# do this first: adjust end of script for reading output files
class Pipeline:

    def __init__(self, name, tmgr, **kwargs):
        self.name = name.replace('.', '_')
        self.tmgr = tmgr

        # control attributes
        self.stage_id    = kwargs.get('stage_id', 0)
        self.passes      = kwargs.get('passes', 1)
        self.num_seqs    = kwargs.get('num_seqs', 10)
        self.seq_rank    = kwargs.get('seq_rank', 0)
        self.is_continued = bool(self.stage_id)
        
        self.iter_seqs   = kwargs.get('iter_seqs', {})
        self.prev_scores = {}
        self.curr_scores = {}

        # pipeline space/sandboxes
        self.base_path        = kwargs.get('base_path', BASE_PATH)
        self.input_path       = f'{self.base_path}/{self.name}_in'
        self.output_path      = (f'{self.base_path}/'
                                 f'af_pipeline_outputs_multi/{self.name}')
        self.output_path_mpnn = f'{self.output_path}/mpnn'
        self.output_path_af   = f'{self.output_path}/af/prediction/best_models'

        # set up mpnn directories if needed
        for pass_idx in range(1, 6):
            job_dir = f'{self.output_path_mpnn}/job_{pass_idx}'
            if not os.path.exists(job_dir):
                os.mkdir(job_dir)

        self.file_list    = []
        self.fasta_list_2 = []
        #might have to do outside of initialization so new pipelines do not run this
        #can be declared directly as argument
        for file_name in os.listdir(f'{self.name}_in'):
            self.fasta_list_2.append(file_name)

    def rank_seqs_by_mpnn_score(self):
        # collect and sort seqs
        job_seqs_dir = f'{self.output_path_mpnn}/job_{self.passes}/seqs'
        for file_name in os.listdir(f'{job_seqs_dir}/'):
            temp = []
            line_ctr=1
            with open(f'{job_seqs_dir}/{file_name}') as fd:
                for x in fd:
                    if line_ctr > 2:
                        if '>' in x:
                            cur_score = float(
                                x.strip().split(',')[2].replace(' score=', ''))
                        else:
                            temp.append([x.strip(), cur_score])
                    line_ctr+=1
            temp.sort(key=lambda x: x[1])
            self.iter_seqs[file_name.split('.')[0]] = temp
        print(self.iter_seqs)

    def submit_next(self):
        next_stage_id = self.stage_id + 1

        if next_stage_id == 2 and not self.is_continued:
            self.rank_seqs_by_mpnn_score()

        elif next_stage_id == 3 and not self.is_continued:
            self.passes = 2

        elif next_stage_id == 5:
            # decision-making process regarding the structure and the sequence
            # (read csv and update self.seq_rank and self.passes accordingly)
            file_name = f'af_stats_{self.name}_pass_{self.passes}.csv'
            with open(file_name) as fd:
                for line in fd.readlines()[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    v = line.split(',')
                    self.curr_scores[v[0].split('.')[0]] = float(v[-1])

            if not self.prev_scores:
                self.prev_scores = dict(self.curr_scores)
            else:
                proteins_to_remove=[]
                # comparison of curr and prev
                for proteins, scores in self.curr_scores.items():
                    if scores > self.prev_scores[proteins]:
                        proteins_to_remove.append(proteins)
                # remove all bad proteins from current pipeline, intialize new pipeline with bad proteins
                # Steps: remove protein from fasta_list_2, remove protein from iter_seqs, store remove iter_seqs subdict separately, pass subdict to new pipeline, set up new dirs for new pipeline, give new pipeline current pass, initialize pipeline with seq_rank +=1
                subdict={}
                #new_fasta_list=[]
                new_name='p'+str(len(PIPELINE_NAMES)+1)
                PIPELINE_NAMES.append(new_name)
                set_up_new_pipeline_dirs(new_name)
                for a in proteins_to_remove:
                    print(a)
                    print(self.curr_scores)
                    print(self.prev_scores)
                    self.fasta_list_2.remove(a+'.pdb')
                    subdict[a]=self.iter_seqs[a]
                    del self.iter_seqs[a]
                    #new_fasta_list.append(a)
                    shutil.copyfile(self.output_path_af+'/'+a+'.pdb',self.base_path+'/'+new_name+'_in/'+a+'.pdb')
                    shutil.move(self.output_path_af+'/'+a+'.pdb',self.base_path+'/af_pipeline_outputs_multi/'+new_name+'/af/prediction/best_models/'+a+'.pdb')
                new_pipelines_queue.put({'name':new_name, 'passes':self.passes, 'iter_seqs':subdict, 'seq_rank':self.seq_rank+1, 'stage_id':3})
        
        elif next_stage_id == 6:
            self.rank_seqs_by_mpnn_score()
            # if we need to create a new Pipeline, then we need to push
            # corresponding inputs into a pipelines queue
            #   new_pipelines_queue.put({'name': .., 'stage_id': ..})

        elif next_stage_id == 7:
            self.passes += 1
            if self.passes <= 4:
                next_stage_id = 3  # loop back to S3

        try:
            submit_stage_func = getattr(self, f'submit_s{next_stage_id}')
        except AttributeError:
            print(f'Pipeline {self.name} has finished')
            return 0

        self.stage_id = next_stage_id
        # submit tasks from the next stage
        return submit_stage_func()

    def submit_s1(self):
        print(f'{self.name}: Stage.1.mpnn.wrapper')
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': ru.generate_id(f'{self.name}.1.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=self.tmgr.session.uid),
            'name': 'T1.initial.mpnn.run',
            'executable': 'python',
            'arguments': [f'{self.base_path}/mpnn_wrapper.py',
                          f'-pdb={self.input_path}/',
                          f'-out={self.output_path_mpnn}/job_{self.passes}/',
                          f'-mpnn={self.base_path}/../../ProteinMPNN/',
                          f'-seqs={self.num_seqs}',
                          '-is_monomer=0',
                          '-chains=A'],
            'pre_exec': TASK_PRE_EXEC
        }))
        return 1

    def submit_s2(self):
        print(f'{self.name}: Stage.2.af.check')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            seq_id   = self.iter_seqs[fastas_0][0]
            print(fastas_0)
            print(self.name)
            print(seq_id)
            tds.append(rp.TaskDescription({
                'uid': ru.generate_id(f'{self.name}.2.%(item_counter)06d',
                                      ru.ID_CUSTOM, ns=self.tmgr.session.uid),
                'name': f'T2.make.fasta.{fastas_0}',
                'executable': 'python',
                'arguments': [f'{self.base_path}/make_af_fasta.py',
                              f'--name={fastas_0}',
                              f'--out={self.name}',
                              f'--seq={seq_id[0]}'],
                'pre_exec': TASK_PRE_EXEC
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s3(self):
        print(f'{self.name}: Stage.3.af2.multi.{self.passes}')
        os.environ['passes'] = str(self.passes)
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            fastas_2 = fastas.split('.')[-2]

            tds.append(rp.TaskDescription({
                'uid': ru.generate_id(f'{self.name}.3.%(item_counter)06d',
                                      ru.ID_CUSTOM, ns=self.tmgr.session.uid),
                'name': f'T3.af2.passes.{fastas_0}{self.passes}',
                'executable': '/bin/bash',
                'arguments': [f'{self.base_path}/af2_multimer_reduced.sh',
                              f'{self.output_path}/af/fasta/{fastas_0}.fa',
                              f'{self.output_path}/af/prediction/dimer_models/'],
                'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
                             'echo $passes >> debug.txt'],
                'post_exec': ['cp '
                              + f'{self.output_path}/af/prediction/'
                              + f'dimer_models/{fastas_2}/*ranked_0*.pdb '
                              + f'{self.output_path}/af/prediction/'
                              + f'best_models/{fastas_2}.pdb',
                              'cp '
                              + f'{self.output_path}/af/prediction/'
                              + f'dimer_models/{fastas_2}/*ranking_debug*.json '
                              + f'{self.output_path}/af/prediction/'
                              + f'best_ptm/{fastas_2}.json'],
                'gpus_per_rank': 1
            }))
            # tds.append(rp.TaskDescription({
            #     'uid': ru.generate_id(f'{self.name}.3.%(item_counter)06d',
            #                           ru.ID_CUSTOM, ns=self.tmgr.session.uid),
            #     'name': f'T3.af2.passes.{fastas_0}{self.passes}',
            #     'executable': 'python',
            #     'arguments': [f'{self.base_path}/dummy_job.py',
            #                   f'--passes={str(self.passes)}'],
            #     'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile',
            #                  'echo $passes >> debug.txt'],
            # }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s4(self):
        print(f'{self.name}: Stage.4.peptides.{self.passes}')
        staged_file = f'af_stats_{self.name}_pass_{self.passes}.csv'
        self.file_list.append(staged_file)
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': ru.generate_id(f'{self.name}.4.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=self.tmgr.session.uid),
            'name': f'T4.peptides.passes.{self.passes}',
            'executable': 'python',
            'arguments': [f'{self.base_path}/plddt_extract_pipeline.py',
                          f'--path={self.base_path}/',
                          f'--iter={self.passes}',
                          f'--out={self.name}'],
            'pre_exec': TASK_PRE_EXEC,
            # download the output of the current task to the current location
            'output_staging': [{'source': f'task:///{staged_file}',
                                'target': f'client:///{staged_file}'}]
        }))
        return 1

    def submit_s5(self):
        print(f'{self.name}: Stage.5.af2structure.{self.passes}')
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': ru.generate_id(f'{self.name}.5.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=self.tmgr.session.uid),
            'name': f'T5.run.mpnn.passes.{self.passes}',
            'executable': 'python',
            'arguments': [f'{self.base_path}/mpnn_wrapper.py',
                          f'-pdb={self.output_path_af}/',
                          f'-out={self.output_path_mpnn}/job_{self.passes}/',
                          f'-mpnn={self.base_path}/../../ProteinMPNN/',
                          f'-seqs={self.num_seqs}',
                          '-is_monomer=0',
                          '-chains=B'],
            'pre_exec': TASK_PRE_EXEC
        }))
        return 1

    def submit_s6(self):
        print(f'{self.name}: Stage.6.af2structure.{self.passes}')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            seq_id   = self.iter_seqs[fastas_0][self.seq_rank]
            print(fastas_0)
            print(self.name)
            print(seq_id)
            tds.append(rp.TaskDescription({
                'uid': ru.generate_id(f'{self.name}.6.%(item_counter)06d',
                                      ru.ID_CUSTOM, ns=self.tmgr.session.uid),
                'name': f'T6.make.fasta.{fastas_0}',
                'executable': 'python',
                'arguments': [f'{self.base_path}/make_af_fasta.py',
                              f'--name={fastas_0}',
                              f'--out={self.name}',
                              f'--seq={seq_id[0]}'],
                'pre_exec': TASK_PRE_EXEC
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s7(self):
        print(f'{self.name}: Stage.7.jon.job')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            fastas_2 = fastas.split('.')[-2]

            tds.append(rp.TaskDescription({
                'uid': ru.generate_id(f'{self.name}.7.%(item_counter)06d',
                                      ru.ID_CUSTOM, ns=self.tmgr.session.uid),
                'name': f'T7.af2.passes.{fastas_0}{self.passes}',
                'executable': '/bin/bash',
                'arguments': [f'{self.base_path}/af2_multimer_reduced.sh',
                              f'{self.output_path}/af/fasta/{fastas_0}.fa',
                              f'{self.output_path}/af/prediction/dimer_models/'],
                'pre_exec': ['. /opt/sw/admin/lmod/lmod/init/profile'],
                'post_exec': ['cp '
                              + f'{self.output_path}/af/prediction/'
                              + f'dimer_models/{fastas_2}/*ranked_0*.pdb '
                              + f'{self.output_path}/af/prediction/'
                              + f'best_models/{fastas_2}.pdb'],
                'gpus_per_rank': 1
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s8(self):
        print(f'{self.name}: Stage.8.find.binders')
        staged_file = f'af_stats_{self.name}_pass_{self.passes}.csv'
        self.file_list.append(staged_file)
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': ru.generate_id(f'{self.name}.8.%(item_counter)06d',
                                  ru.ID_CUSTOM, ns=self.tmgr.session.uid),
            'name': 'T8.find.binders',
            'executable': 'python',
            'arguments': [f'{self.base_path}/plddt_extract_pipeline.py',
                          f'--path={self.base_path}/',
                          f'--iter={self.passes}',
                          f'--out={self.name}'],
            'pre_exec': TASK_PRE_EXEC,
            'output_staging': [{'source': f'task:///{staged_file}',
                                'target': f'client:///{staged_file}'}]
        }))
        return 1

def set_up_new_pipeline_dirs(pipe_name):
    if not os.path.isdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name):
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name)
        os.mkdir(BASE_PATH+'/'+pipe_name+'_in/')
        #af
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/fasta/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/prediction/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/prediction/best_models/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/prediction/best_ptm/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/prediction/dimer_models/')
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/af/prediction/logs/')
        #mpnn
        os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/mpnn/')
        for i in range(1,6): 
            #if os.path.exists(output_path_mpnn+"job_"+str(i))==False:
            os.mkdir(BASE_PATH+'/af_pipeline_outputs_multi/'+pipe_name+'/mpnn/job_'+str(i))


def task_state_cb(task, state):
    if state not in rp.FINAL:
        # ignore all non-finished state transitions
        return
    pipe_name = task.uid.split('.', 1)[0]
    tasks_finished_queue.put([pipe_name, task.state])
    print(tasks_finished_queue)


def main():
    session = rp.Session()
    pmgr = rp.PilotManager(session)
    tmgr = rp.TaskManager(session)
    tmgr.register_callback(task_state_cb)
    pilot = pmgr.submit_pilots(rp.PilotDescription({
        'resource': 'rutgers.amarel',
        'runtime' : 4320,
        #'runtime': 60,
        'cores'   : 4,
        'gpus'    : 4
    }))

    tmgr.add_pilots(pilot)
    pilot.wait(rp.PMGR_ACTIVE)

    # create pipelines
    pipes = {p: Pipeline(p, tmgr) for p in PIPELINE_NAMES}

    my_dict = {}
    for pipe_name in pipes:
        for file_name in os.listdir(f'{pipe_name}_in/'):
            my_dict[file_name.split('.')[0]] = []
    fasta_list = []
    for f in my_dict.keys():
        fasta_list.append(f)

    # start executing pipelines (submit S1s)
    tasks_active = defaultdict(int)
    for pipe_name, pipe in pipes.items():
        # start each pipeline
        tasks_active[pipe_name] += pipe.submit_next()  # num submitted tasks
    print('here')
    print(tasks_active)
    # loop to track the status of the executed tasks and to submit next stages
    while True:
        #print('start')
        try:
            pipe_name, task_state = tasks_finished_queue.get_nowait()
            print(pipe_name)
            print(task_state)
        except queue.Empty:
            #print('empty')
            continue
        tasks_active[pipe_name] -= 1
        print(tasks_active)
        if tasks_active[pipe_name]:
            continue

        tasks_active[pipe_name] += pipes[pipe_name].submit_next()

        # check if there is a request to create a new pipeline
        try:
            pipeline_inputs = new_pipelines_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            pipe_name = pipeline_inputs['name']
            pipes[pipe_name] = Pipeline(tmgr=tmgr, **pipeline_inputs)
            # start the new pipeline
            tasks_active[pipe_name] += pipes[pipe_name].submit_next()

        # if there is no active tasks, then all pipelines finished
        if not sum(tasks_active.values()):
            break

    session.close(download=True)

    all_files = []
    for pipe in pipes.values():
        all_files += pipe.file_list

    for a in all_files:
        df = pd.read_csv(a)
        names = df['ID']
        plddt = df['avg_plddt']
        ptm = df['ptm']
        pae = df['avg_pae']
        cur_round = a.split('_')[-1].replace('.csv','')
        for files in fasta_list:
            print('FILE: ' + files)
            for keys, values in my_dict.items():
                if keys == files.split('.')[0]:
                    print('KEY: ' + keys)
                    for x, y, z, w in zip(names, plddt, ptm, pae):
                        if x.split('.')[0] == files.split('.')[0]:
                            print('APPEND')
                            temp_plddt = y
                            temp_ptm = z
                            temp_pae = w
                            my_dict[keys].append('plddt: ' + str(
                                temp_plddt) + " pae: " + str(
                                temp_pae) + ' round: ' + cur_round)
                            break

    print(my_dict)
    with open('af_pipeline_output_summary.jsonl', 'w') as f:
        f.write(str(my_dict))


if __name__ == '__main__':
    main()


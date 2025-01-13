#!/usr/bin/env python

import argparse
import copy
import os
import pandas as pd
import queue
import shutil
import sys

from collections import defaultdict

from pyrosetta import *
init()

import radical.pilot as rp
import radical.utils as ru

tasks_finished_queue = queue.Queue()
new_pipelines_queue  = queue.Queue()

# if "base_path" is not provided, then "base_path" is the current directory
MODULE_PATH = os.path.abspath(os.path.dirname(__file__))


class Pipeline:

    def __init__(self, name, tmgr, config, **kwargs):
        self.name = name.replace('.', '_')
        self.tmgr = tmgr
        # pipeline config
        self.cfg = ru.TypedDict(config)

        # pipeline space/sandboxes (absolute paths)
        self.dirs = generate_dir_names(name=self.name,
                                       base_path=kwargs.get('base_path'))

        # control attributes
        self.stage_id     = kwargs.get('stage_id', 0)
        self.passes       = kwargs.get('passes', 1)
        self.num_seqs     = kwargs.get('num_seqs', 10)
        self.seq_rank     = kwargs.get('seq_rank', 0)
        self.is_continued = bool(self.stage_id)
        
        self.iter_seqs    = kwargs.get('iter_seqs', {})
        self.prev_scores  = kwargs.get('prev_scores', {})
        self.curr_scores  = {}

        # order id of a pipeline within the chain of sub-pipelines per structure
        # "parent"-pipeline's order equals to "0"
        self.sub_order    = kwargs.get('sub_order', 0)

        # set up mpnn directories if needed
        for pass_idx in range(1, 6):
            ru.rec_makedir(f'{self.dirs.output_mpnn}/job_{pass_idx}')

        self.file_list    = []
        self.fasta_list_2 = []
        # might have to do outside of initialization, so new pipelines
        # do not run this can be declared directly as argument
        for file_name in os.listdir(self.dirs.input):
            self.fasta_list_2.append(file_name)

        self.reporter = self.tmgr.session._rep

    def rank_seqs_by_mpnn_score(self):
        # collect and sort seqs
        with os.scandir(f'{self.dirs.output_mpnn}/job_{self.passes}/seqs') as d:
            for entry in d:
                temp = []
                with open(entry.path) as f:
                    for line in f.readlines()[2:]:
                        if '>' in line:
                            cur_score = line.strip().split(',')[2]
                            cur_score = float(cur_score.replace(' score=', ''))
                        else:
                            temp.append([line.strip(), cur_score])
                temp.sort(key=lambda x: x[1])
                self.iter_seqs[entry.name.split('.')[0]] = temp

        self.reporter.plain(f'<<{self.name} - '
                            f'iter-seqs: {self.iter_seqs}\n')

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
            with open(f'{self.dirs.base}/{file_name}') as fd:
                for line in fd.readlines()[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    v = line.split(',')
                    self.curr_scores[v[0].split('.')[0]] = float(v[-1])

            self.reporter.plain(f'<<{self.name} - '
                                f'curr-scores: {self.curr_scores}\n')

            if not self.prev_scores:
                self.prev_scores = copy.deepcopy(self.curr_scores)
            else:
                # remove all bad proteins from current pipeline,
                # initialize new pipeline with bad proteins
                # Steps: - remove protein from fasta_list_2;
                #        - remove protein from iter_seqs;
                #        - store removed iter_seqs (sub_iter_seqs) separately;
                #        - pass sub_iter_seqs to new pipeline;
                #        - set up new dirs for new pipeline;
                #        - give new pipeline current pass;
                #        - initialize pipeline with seq_rank +1.
                sub_iter_seqs = {}
                # comparison of curr and prev
                for proteins, scores in self.curr_scores.items():
                    if scores > self.prev_scores[proteins]:
                        # skip if the protein is not in the dict
                        if not self.iter_seqs.get(proteins):
                            continue
                        # proteins to be removed from the current pipeline
                        sub_iter_seqs[proteins] = self.iter_seqs.pop(proteins)

                # create new pipeline (if applicable)
                if sub_iter_seqs and self.sub_order < self.cfg.max_sub_pipelines:

                    new_sub_order = self.sub_order + 1
                    new_name      = f'{self.name}_{new_sub_order}'

                    new_dirs = set_up_pipeline_dirs(name=new_name,
                                                    base_path=self.dirs.base)
                    for a in sub_iter_seqs:
                        shutil.copyfile(f'{self.dirs.af_best_models}/{a}.pdb',
                                        f'{new_dirs.input}/{a}.pdb')

                    new_pipelines_queue.put({
                        'name'       : new_name,
                        'sub_order'  : new_sub_order,
                        'passes'     : self.passes,
                        'iter_seqs'  : sub_iter_seqs,
                        'seq_rank'   : self.seq_rank + 1,
                        'prev_scores': copy.deepcopy(self.prev_scores),
                        'stage_id'   : 1})

                # finalize the "cleanup" of the current pipeline
                for a in sub_iter_seqs:
                    del self.curr_scores[a]
                    self.fasta_list_2.remove(f'{a}.pdb')
                    os.unlink(f'{self.dirs.af_best_models}/{a}.pdb')
                    os.unlink(f'{self.dirs.af_fasta}/{a}.fa')
                self.prev_scores = copy.deepcopy(self.curr_scores)
        
        elif next_stage_id == 6:
            self.rank_seqs_by_mpnn_score()

        elif next_stage_id == 7:
            self.passes += 1
            if self.passes <= 4:
                next_stage_id = 3  # loop back to S3

        try:
            submit_stage_func = getattr(self, f'submit_s{next_stage_id}')
        except AttributeError:
            self.reporter.info(f'<<Pipeline {self.name} has finished')
            self.reporter.ok('>>ok\n')
            return 0

        self.stage_id = next_stage_id
        # submit tasks from the next stage
        return submit_stage_func()

    def _generate_uid(self):
        return ru.generate_id(f'{self.name}.{self.stage_id}.%(item_counter)06d',
                              ru.ID_CUSTOM, ns=self.tmgr.session.uid)

    def submit_s1(self):
        self.reporter.info(f'<<{self.name}: Stage.1.mpnn.wrapper')
        self.reporter.ok('>>started\n')
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': self._generate_uid(),
            'name': 'T1.initial.mpnn.run',
            'executable': 'python',
            'arguments': [
                f'{self.dirs.base}/mpnn_wrapper.py',
                f'-pdb={self.dirs.input}/',
                f'-out={self.dirs.output_mpnn}/job_{self.passes}/',
                f'-mpnn={self.dirs.base}/ProteinMPNN/',
                f'-seqs={self.num_seqs}',
                '-is_monomer=0',
                '-chains=A'],
            'pre_exec': self.cfg.task_pre_exec.base
        }))
        return 1

    def submit_s2(self):
        self.reporter.info(f'<<{self.name}: Stage.2.af.check')
        self.reporter.ok('>>started\n')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            seq_id   = self.iter_seqs[fastas_0][self.seq_rank]
            self.reporter.plain(f'<<{self.name} - {self.stage_id} - '
                                f'{fastas_0} {seq_id}\n')
            tds.append(rp.TaskDescription({
                'uid': self._generate_uid(),
                'name': f'T2.make.fasta.{fastas_0}',
                'executable': 'python',
                'arguments': [
                    f'{self.dirs.base}/make_af_fasta.py',
                    f'--name={fastas_0}',
                    f'--out={self.name}',
                    f'--seq={seq_id[0]}'],
                'pre_exec': self.cfg.task_pre_exec.base
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s3(self):
        self.reporter.info(f'<<{self.name}: Stage.3.af2.multi.{self.passes}')
        self.reporter.ok('>>started\n')
        os.environ['passes'] = str(self.passes)
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0     = fastas.split('.')[0]
            fastas_2     = fastas.split('.')[-2]
            src_fastas_2 = f'{self.dirs.af_dimer_models}/{fastas_2}'
            tds.append(rp.TaskDescription({
                'uid': self._generate_uid(),
                'name': f'T3.af2.passes.{fastas_0}{self.passes}',
                'executable': '/bin/bash',
                'named_env': 'bs0',
                'arguments': [
                    f'{self.dirs.base}/af2_multimer_reduced.sh',
                    f'{self.dirs.af_fasta}/',
                    f'{fastas_0}.fa',
                    f'{self.dirs.af_dimer_models}/'],
                'pre_exec': self.cfg.task_pre_exec.af,
                'post_exec': [
                    f'cp {src_fastas_2}/*ranked_0*.pdb '
                    + f'{self.dirs.af_best_models}/{fastas_2}.pdb',
                    f'cp {src_fastas_2}/*ranking_debug*.json '
                    + f'{self.dirs.af_best_ptm}/{fastas_2}.json',
                    f'cp {src_fastas_2}/*ranked_0*.pdb '
                    + f'{self.dirs.output_mpnn}/job_{self.passes-1}/'
                    + f'{fastas_2}.pdb'],
                'gpus_per_rank': 1
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s4(self):
        self.reporter.info(f'<<{self.name}: Stage.4.peptides.{self.passes}')
        self.reporter.ok('>>started\n')
        staged_file = f'af_stats_{self.name}_pass_{self.passes}.csv'
        self.file_list.append(staged_file)
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': self._generate_uid(),
            'name': f'T4.peptides.passes.{self.passes}',
            'executable': 'python',
            'arguments': [
                f'{self.dirs.base}/plddt_extract_pipeline.py',
                f'--path={self.dirs.base}/',
                f'--iter={self.passes}',
                f'--out={self.name}'],
            'pre_exec': self.cfg.task_pre_exec.base,
            # download the output of the task to the base dir
            'output_staging': [{'source': f'task:///{staged_file}',
                                'target': f'{self.dirs.base}/{staged_file}'}]
        }))
        return 1

    def submit_s5(self):
        self.reporter.info(f'<<{self.name}: Stage.5.af2structure.{self.passes}')
        self.reporter.ok('>>started\n')
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': self._generate_uid(),
            'name': f'T5.mpnn.passes.{self.passes}',
            'executable': 'python',
            'arguments': [f'{self.dirs.base}/mpnn_wrapper.py',
                          f'-pdb={self.dirs.output_af}/',
                          f'-out={self.dirs.output_mpnn}/job_{self.passes}/',
                          f'-mpnn={self.dirs.base}/ProteinMPNN/',
                          f'-seqs={self.num_seqs}',
                          '-is_monomer=0',
                          '-chains=B'],
            'pre_exec': self.cfg.task_pre_exec.base
        }))
        return 1

    def submit_s6(self):
        self.reporter.info(f'<<{self.name}: Stage.6.af2structure.{self.passes}')
        self.reporter.ok('>>started\n')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0 = fastas.split('.')[0]
            # always use 0 for rank_seq in this stage
            seq_id   = self.iter_seqs[fastas_0][0]
            self.reporter.plain(f'<<{self.name} - {self.stage_id} - '
                                f'{fastas_0} {seq_id}\n')
            tds.append(rp.TaskDescription({
                'uid': self._generate_uid(),
                'name': f'T6.make.fasta.{fastas_0}',
                'executable': 'python',
                'arguments': [
                    f'{self.dirs.base}/make_af_fasta.py',
                    f'--name={fastas_0}',
                    f'--out={self.name}',
                    f'--seq={seq_id[0]}'],
                'pre_exec': self.cfg.task_pre_exec.base
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s7(self):
        self.reporter.info(f'<<{self.name}: Stage.7.jon.job')
        self.reporter.ok('>>started\n')
        tds = []
        for fastas in self.fasta_list_2:
            fastas_0     = fastas.split('.')[0]
            fastas_2     = fastas.split('.')[-2]
            src_fastas_2 = f'{self.dirs.af_dimer_models}/{fastas_2}'
            tds.append(rp.TaskDescription({
                'uid': self._generate_uid(),
                'name': f'T7.af2.passes.{fastas_0}{self.passes}',
                'executable': '/bin/bash',
                'named_env': 'bs0',
                'arguments': [
                    f'{self.dirs.base}/af2_multimer_reduced.sh',
                    f'{self.dirs.af_fasta}/',
                    f'{fastas_0}.fa',
                    f'{self.dirs.af_dimer_models}/'],
                'pre_exec': self.cfg.task_pre_exec.af,
                'post_exec': [
                    f'cp {src_fastas_2}/*ranked_0*.pdb '
                    + f'{self.dirs.af_best_models}/{fastas_2}.pdb',
                    f'cp {src_fastas_2}/*ranking_debug*.json '
                    + f'{self.dirs.af_best_ptm}/{fastas_2}.json',
                    f'cp {src_fastas_2}/*ranked_0*.pdb '
                    + f'{self.dirs.output_mpnn}/job_{self.passes-1}/'
                    + f'{fastas_2}.pdb'],
                'gpus_per_rank': 1
            }))
        tasks = ru.as_list(self.tmgr.submit_tasks(tds))
        return len(tasks)

    def submit_s8(self):
        self.reporter.info(f'<<{self.name}: Stage.8.find.binders')
        self.reporter.ok('>>started\n')
        staged_file = f'af_stats_{self.name}_pass_{self.passes}.csv'
        self.file_list.append(staged_file)
        self.tmgr.submit_tasks(rp.TaskDescription({
            'uid': self._generate_uid(),
            'name': 'T8.find.binders',
            'executable': 'python',
            'arguments': [
                f'{self.dirs.base}/plddt_extract_pipeline.py',
                f'--path={self.dirs.base}/',
                f'--iter={self.passes}',
                f'--out={self.name}'],
            'pre_exec': self.cfg.task_pre_exec.base,
            'output_staging': [
                {'source': f'task:///{staged_file}',
                 'target': f'{self.dirs.base}/{staged_file}'}]
        }))
        return 1


def generate_dir_names(name, base_path=None):
    base_path = base_path or MODULE_PATH
    dirs = {
        'base'           : base_path,
        'input'          : f'{base_path}/{name}_in',
        'output_base'    : f'{base_path}/af_pipeline_outputs_multi/{name}'}
    dirs.update({
        'output_mpnn'    : f'{dirs["output_base"]}/mpnn',
        'output_af'      : f'{dirs["output_base"]}/af'})
    dirs.update({
        'af_fasta'       : f'{dirs["output_af"]}/fasta',
        'af_best_models' : f'{dirs["output_af"]}/prediction/best_models',
        'af_best_ptm'    : f'{dirs["output_af"]}/prediction/best_ptm',
        'af_dimer_models': f'{dirs["output_af"]}/prediction/dimer_models',
        'af_logs'        : f'{dirs["output_af"]}/prediction/logs'})
    return ru.TypedDict(dirs)


def set_up_pipeline_dirs(name, base_path=None):
    dirs = generate_dir_names(name, base_path)
    if not os.path.isdir(dirs.output_base):
        for dir_name in dirs.keys():
            ru.rec_makedir(dirs[dir_name])
        # mpnn
        for pass_idx in range(1, 6):
            ru.rec_makedir(f'{dirs.output_mpnn}/job_{pass_idx}')
    return dirs


def task_state_cb(task, state):
    if state not in rp.FINAL:
        # ignore all non-finished state transitions
        return
    pipe_name = task.uid.split('.', 1)[0]
    tasks_finished_queue.put([pipe_name, task.state])


def main(args):

    # read configuration
    config_file = args.config_file
    if '/' not in config_file:
        config_file = os.path.join(MODULE_PATH, config_file)
    cfg = ru.read_json(config_file)

    for k, v in cfg.get('env', {}).items():
        os.environ[k] = v

    # create RADICAL Session and Task-/Pilot-Managers
    session = rp.Session()
    pmgr    = rp.PilotManager(session)
    tmgr    = rp.TaskManager(session)

    pilot   = pmgr.submit_pilots(rp.PilotDescription(cfg['run_description']))
    tmgr.add_pilots(pilot)
    tmgr.register_callback(task_state_cb)

    pilot.wait(rp.PMGR_ACTIVE)
    pilot.prepare_env('bs0', {'type': 'shell'})

    # create pipelines
    pipes = {p: Pipeline(p, tmgr, cfg.get('pipeline_config', {}),
                         base_path=cfg['main']['base_path'])
             for p in cfg['main']['pipeline_names']}

    my_dict = {}
    for pipe in pipes.values():
        for file_name in os.listdir(pipe.dirs.input):
            my_dict[file_name.split('.')[0]] = []
    fasta_list = []
    for f in my_dict.keys():
        fasta_list.append(f)

    # start executing pipelines (submit S1s)
    tasks_active = defaultdict(int)
    for pipe_name, pipe in pipes.items():
        # start each pipeline
        tasks_active[pipe_name] += pipe.submit_next()  # num submitted tasks

    # loop to track the status of the executed tasks and to submit next stages
    while True:
        try:
            pipe_name, task_state = tasks_finished_queue.get_nowait()
        except queue.Empty:
            continue

        # dump session org data (registry, tmgr, pmgr)
        try   : session.dump()
        except: pass

        tasks_active[pipe_name] -= 1
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
            pipeline_inputs.update(config=cfg.get('pipeline_config', {}),
                                   base_path=cfg['main']['base_path'])
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
                            my_dict[keys].append(f'plddt: {y} pae: {w} '
                                                 f'round: {cur_round}')
                            break

    with open('af_pipeline_output_summary.jsonl', 'w') as f:
        f.write(str(my_dict))


def get_args():
    parser = argparse.ArgumentParser(
        description='Run the IMPRESS workflow application',
        usage='<impress app> [-c/--config <config file>]')
    parser.add_argument(
        '-c', '--config',
        dest='config_file',
        type=str,
        help='config file',
        required=False)
    return parser.parse_args(sys.argv[1:])


if __name__ == '__main__':
    main(args=get_args())


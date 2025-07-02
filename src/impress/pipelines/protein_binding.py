import os
from .impress_pipeline import ImpressBasePipeline

TASK_PRE_EXEC = []


class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs={}, **kwargs):
        # Execution metadata
        self.step_id = kwargs.get('step_id', 1)
        self.sub_order = kwargs.get('sub_order', 0)
        self.passes = kwargs.get('passes', 1)
        self.num_seqs = kwargs.get('num_seqs', 10)

        # Sequence and score state
        self.iter_seqs = kwargs.get('iter_seqs', {})
        self.current_scores = {}
        self.previous_scores = kwargs.get('previous_score', {})

        # Input-related
        self.fasta_list_2 = kwargs.get('fasta_list_2', [])
        self.base_path = kwargs.get('base_path', '/home/x-aymen/IMPRESS-Framework/examples')
        self.input_path = f'{self.base_path}/{name}_in'

        # Output paths
        self.output_path = f'{self.base_path}/af_pipeline_outputs_multi/{name}'
        self.output_path_mpnn = f'{self.output_path}/mpnn'
        self.output_path_af = f'{self.output_path}/af/prediction/best_models'

        # Initialize base class (this will call register_pipeline_tasks)
        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self):
        """Register all pipeline tasks"""
        
        @self.auto_register_task()  # MPNN
        async def s1():
            mpnn_script = f"{self.base_path}/mpnn_wrapper.py"
            output_dir = f"{self.output_path_mpnn}/job_{self.passes}/"
            mpnn_model = f"{self.base_path}/../../ProteinMPNN/"

            return (
                f"python3 {mpnn_script} "
                f"-pdb={self.input_path} "
                f"-out={output_dir} "
                f"-mpnn={mpnn_model} "
                f"-seqs={self.num_seqs} "
                "-is_monomer=0 "
                "-chains=A"
            )

        async def s2():
            job_seqs_dir = f'{self.output_path_mpnn}/job_{self.passes}/seqs'

            for file_name in os.listdir(job_seqs_dir):
                seqs = []
                with open(os.path.join(job_seqs_dir, file_name)) as fd:
                    lines = fd.readlines()[2:]  # Skip first two lines

                score = None
                for line in lines:
                    line = line.strip()
                    if line.startswith('>'):
                        score = float(line.split(',')[2].replace(' score=', ''))
                    else:
                        seqs.append([line, score])

                seqs.sort(key=lambda x: x[1])  # Sort by score
                self.iter_seqs[file_name.split('.')[0]] = seqs
            
            print(self.iter_seqs)


        # fasta - don't use helper script - cannot run x tasks for x structures
        async def s3():
            output_dir = os.path.join(self.output_path, self.name, 'af', 'fasta')

            for fasta_file in self.fasta_list_2:
                print(fasta_file)
                base_name = fasta_file.split('.')[0]
                design_seq = self.iter_seqs[base_name][self.seq_rank][0]
                pep_seq = 'EGYQDYEPEA'

                fasta_path = os.path.join(output_dir, f'{base_name}.fa')
                with open(fasta_path, 'w') as f:
                    f.write(f'>pdz\n{design_seq}\n>pep\n{pep_seq}\n')


        @self.auto_register_task()  # alphafold, must be run separately for each structure one at a time!
        async def s4(target_fasta, task_description={}):
            return (
                f"/bin/bash {self.base_path}/af2_multimer_reduced.sh "
                f'{self.output_path}/af/fasta/{target_fasta}.fa '
                f'{self.output_path}/af/prediction/dimer_models/')

        @self.auto_register_task()  # plddt_extract
        async def s5():
            return (
                f"python3 {self.base_path}/plddt_extract_pipeline.py "
                f"--path={self.base_path} "
                f"--iter={self.passes} "
                f"--out={self.name}")

    async def get_scores_map(self):
        """Return current and previous scores"""
        return {
            'c_scores': self.current_scores,
            'p_scores': self.previous_scores
        }

    async def finalize(self):
        """Finalization logic"""
        return

    def get_current_config_for_next_pipeline(self):
        """Return configuration for next pipeline"""
        return {
            "name": "adaptively_generate_pipeline",
            "type": ProteinBindingPipeline
        }

    async def run(self):
        """Main execution logic"""
        s1_res = await self.s1()
        print(s2_res)

        s2_res = await self.s2()
        print(s2_res)
        
        s3_res = await self.s3()
        print(s3_res)

        '''
        models_path = f"{self.output_path}/af/prediction/dimer_models/{target_fasta}"
        s4_description = {
            'pre_exec': [
                '. /opt/sw/admin/lmod/lmod/init/profile', TASK_PRE_EXEC
            ],
            'post_exec': [
                f"cp {models_path}/*ranked_0*.pdb {self.output_path}/af/prediction/best_models/{target_fasta}.pdb",
                f"cp {models_path}/*ranking_debug*.json {self.output_path}/af/prediction/best_ptm/{target_fasta}.json",
                f"cp {models_path}/*ranked_0*.pdb {self.output_path}/mpnn/job_{self.passes - 1}/{target_fasta}.pdb",
            ]
        }

        s4_res = await self.s4(target_fasta=s3_res, task_description=s4_description)
        s5_res = await self.s5()
        '''

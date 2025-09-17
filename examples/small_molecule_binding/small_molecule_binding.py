import asyncio
import copy
import os

from impress.pipelines.impress_pipeline import ImpressBasePipeline

TASK_PRE_EXEC = [
    "conda activate ve.impress" # local
#    "module load anaconda",
#    "source activate base",
#    (f"conda activate /anvil/scratch/{os.environ['USER']}/impress/ve.impress"),
]

class SmallMoleculeBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        # Execution metadata
        if configs is None:
            configs = {}
        self.passes = kwargs.get("passes", 1)
        self.step_id = kwargs.get("step_id", 1)
        self.seq_rank = kwargs.get("seq_rank", 0)
        self.num_seqs = kwargs.get("num_seqs", 10)
        self.sub_order = kwargs.get("sub_order", 0)
        self.max_passes = kwargs.get("max_passes", 1)

#        # Sequence and score state
        self.current_scores = {}
        self.iter_seqs = kwargs.get("iter_seqs", {})
        self.previous_scores = kwargs.get("previous_score", {})

        super().__init__(name, flow, **configs, **kwargs)

#        # Input-related
#        self.fasta_list_2 = kwargs.get("fasta_list_2", [])
        self.base_path = kwargs.get("base_path", os.getcwd())
        self.input_path = os.path.join(self.base_path, f"{self.name}_in")
        self.mpnn_dir = kwargs.get("mpnn_dir", f"{self.base_path}/LigandMPNN")

#        # Output paths
        self.output_path = os.path.join(
            self.base_path, "/myoutputs", self.name
        )
        self.output_path_packmin = os.path.join(self.output_path, "/packmin")
        self.output_path_lmpnn = os.path.join(
            self.output_path, "/lmpnn"
        )

    def set_up_new_pipeline_dirs(self, new_pipeline_name):
        base_output = os.path.join(
            self.base_path, "af_pipeline_outputs_multi", new_pipeline_name
        )
        input_dir = os.path.join(self.base_path, f"{new_pipeline_name}_in")

        if os.path.isdir(base_output):
            return  # already exists, nothing to do

    def register_pipeline_tasks(self):
        """Register all pipeline tasks"""
        
        #packmin 1
        @self.auto_register_task()
        async def s1():
            self.taskcount=1
            self.s1_dirs=f"{self.base_path}/s1"
            os.makedirs(f"{self.s1_dirs}/in",exist_ok=True)
            os.makedirs(f"{self.s1_dirs}/out",exist_ok=True) 

            input_dir= self.input_path #TODO if self.passes==1 else f"{self.base_path}"
            pdb_file="3rk4.pdb"
            lig_file="RED.params"
            pdb_path=f"{input_dir}/{pdb_file}"
            lig_path=f"{input_dir}/{lig_file}"
            output_dir=f"{self.s1_dirs}/out"

            return(
                f"python {self.base_path}/packmin.py "
                f"{pdb_path} "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        #lmpnn 1
        @self.auto_register_task()
        async def s2():
            self.taskcount=2
            self.s2_dirs=f"{self.base_path}/s2"
            os.makedirs(f"{self.s2_dirs}/in",exist_ok=True)
            os.makedirs(f"{self.s2_dirs}/out",exist_ok=True) 

            input_dir=f"{self.s1_dirs}/out"
            pdb_file=os.listdir(f"{self.s1_dirs}/out")[0]
            pdb_path=f"{input_dir}/{pdb_file}"
            output_dir=f"{self.s2_dirs}/out"

            return(
                f"bash {self.base_path}/mpnn_wrapper.sh "
                f"{pdb_path} "
                f"{output_dir} "
                f"{self.mpnn_dir} "
            )

        #packmin 2
        @self.auto_register_task()
        async def s3():
            self.taskcount=3
            self.s3_dirs=f"{self.base_path}/s3"
            os.makedirs(f"{self.s3_dirs}/in",exist_ok=True)
            os.makedirs(f"{self.s3_dirs}/out",exist_ok=True) 

            input_dir=f"{self.s2_dirs}/out/packed"
            pdb_file=os.listdir(input_dir)[0]
            lig_file="RED.params"
            pdb_path=f"{input_dir}/{pdb_file}"
            lig_path=f"{self.input_path}/{lig_file}"
            output_dir=f"{self.s3_dirs}/out"

            return(
                f"python {self.base_path}/packmin.py "
                f"{pdb_path} "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        #lmpnn 2
        @self.auto_register_task()
        async def s4():
            self.taskcount=4
            self.s4_dirs=f"{self.base_path}/s4"
            os.makedirs(f"{self.s4_dirs}/in",exist_ok=True)
            os.makedirs(f"{self.s4_dirs}/out",exist_ok=True) 

            input_dir=f"{self.s3_dirs}/out"
            pdb_file=os.listdir(f"{self.s3_dirs}/out")[0]
            pdb_path=f"{input_dir}/{pdb_file}"
            output_dir=f"{self.s4_dirs}/out"

            return(
                f"bash {self.base_path}/mpnn_wrapper.sh "
                f"{pdb_path} "
                f"{output_dir} "
                f"{self.mpnn_dir} "
            )

    async def get_scores_map(self):
        """Return current and previous scores"""
        return {"c_scores": self.current_scores, "p_scores": self.previous_scores}

    # TODO update this logic for the new wf
    def finalize(self, sub_iter_seqs):
        # finalize the "cleanup" of the current pipeline
        for a in sub_iter_seqs:
            self.fasta_list_2.remove(f"{a}.pdb")
            os.unlink(f"{self.output_path_af}/{a}.pdb")
            os.unlink(f"{self.output_path}/af/fasta/{a}.fa")
        self.previous_scores = copy.deepcopy(self.current_scores)

    async def run(self):
        """Main execution logic"""

        self.logger.pipeline_log(f"Running for a maximum of {self.max_passes} passes")

        while self.passes <= self.max_passes:
            self.logger.pipeline_log(f"Starting pass {self.passes}")

            # TODO task for initial lmpnn to create 8 outputs

            self.logger.pipeline_log("running packmin 1")
            await self.s1(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("packmin finished")

            self.logger.pipeline_log("running lmpnn 1")
            await self.s2(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("lmpnn finished")

            self.logger.pipeline_log("running packmin 2")
            await self.s3(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("packmin finished")

            self.logger.pipeline_log("running lmpnn 2")
            await self.s4(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("lmpnn finished")
            
            # TODO subsequent tasks packmin, lmpnn, fastrelax, etc

            await self.run_adaptive_step(wait=True)

            self.passes += 1

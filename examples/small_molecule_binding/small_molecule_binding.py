import asyncio
import copy
import os
import subprocess
import sys

from impress.pipelines.impress_pipeline import ImpressBasePipeline

TASK_PRE_EXEC = [
#    "source /home/mason/exdrive/rad/env_impress/bin/activate"
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
        self.scripts_path = os.path.join(self.base_path, "scripts")
        self.pipeline_inputs = os.path.join(self.base_path, f"{self.name}_in")
        self.mpnn_dir = kwargs.get("mpnn_dir", f"{self.base_path}/LigandMPNN")

#        # Output paths
        self.output_path = os.path.join(
            self.base_path, "/myoutputs", self.name
        )
        self.output_path_packmin = os.path.join(self.output_path, "/packmin")
        self.output_path_lmpnn = os.path.join(
            self.output_path, "/lmpnn"
        )
        
        self.taskcount = 0
        self.previous_task = "START"

    def set_up_new_pipeline_dirs(self, new_pipeline_name):
        base_output = os.path.join(
            self.base_path, "af_pipeline_outputs_multi", new_pipeline_name
        )
        input_dir = os.path.join(self.base_path, f"{new_pipeline_name}_in")

        if os.path.isdir(base_output):
            return  # already exists, nothing to do

    def register_pipeline_tasks(self):
        """Register all pipeline tasks"""

        #lmpnn
        @self.auto_register_task()
        async def mpnn(fixed_residues_file:str | None = None):
            """
            Sequence generation. Follows backbone generation.
            """
            self.taskcount=self.taskcount+1
            input_dir=f"{str(self.taskcount-1)}_{self.previous_task}/out"
            print(f"Task count is {self.taskcount}")
            taskname = "mpnn"
            self.previous_task = taskname
            taskdir = f"{self.base_path}/{str(self.taskcount)}_{taskname}"
            os.makedirs(f"{taskdir}/in",exist_ok=True)
            os.makedirs(f"{taskdir}/out",exist_ok=True) 

            pdb_file=os.listdir(f"{input_dir}")[0]
            pdb_path=f"{input_dir}/{pdb_file}"
            output_dir=f"{taskdir}/out"

#            fixed_residues_file = f"{self.pipeline_inputs}/fixed_residues.txt"
            if fixed_residues_file:
                fixed_residues = os.system(f"cat {fixed_residues_file}")                
                fixed_residues_line = f"""--fixed_residues {ligand_mpnn} \ """
            else: fixed_residues=""

            return(
                f"""python {self.mpnn_dir}/run.py \
                --model_type "ligand_mpnn" \
                --checkpoint_path_sc {self.mpnn_dir}/model_params/ligandmpnn_sc_v_32_002_16.pt \
                --checkpoint_ligand_mpnn {self.mpnn_dir}/model_params/ligandmpnn_v_32_010_25.pt \
                --seed 111 \
                --pdb_path {pdb_path} \
                --out_folder {output_dir} \
                --pack_side_chains 1 \
                --number_of_batches 1 \
                --batch_size 1 \
                --number_of_packs_per_design 1 \
                --pack_with_ligand_context 1 \
                --repack_everything 1 \
                --temperature 0.1 \
                """ + fixed_residues_line
            )

#            return(
#                f"bash {self.scripts_path}/mpnn_wrapper.sh "
#                f"{pdb_path} "
#                f"{output_dir} "
#                f"{self.mpnn_dir} "
#            )
        
        #packmin
        @self.auto_register_task()
        async def packmin():
            """
            SC rotamer packing. Follows sequence generation.
            """
            self.taskcount=self.taskcount+1
            input_dir=f"{str(self.taskcount-1)}_{self.previous_task}/out"
            print(f"Task count is {self.taskcount}")
            taskname = "packmin"
            self.previous_task = taskname
            taskdir = f"{self.base_path}/{str(self.taskcount)}_{taskname}"
            os.makedirs(f"{taskdir}/in",exist_ok=True)
            os.makedirs(f"{taskdir}/out",exist_ok=True)

            lig_file = "ALR.params"
            lig_path=f"{self.pipeline_inputs}/{lig_file}"
            pdb_dir = f"{input_dir}/packed"
            pdb_file = os.listdir(pdb_dir)[0]
            output_dir=f"{taskdir}/out"

            return(
                f"python {self.scripts_path}/packmin.py "
                f"{pdb_dir}/{pdb_file} "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        #fast relax
        @self.auto_register_task()
        async def fastrelax():
            """
            Rosetta FastRelax. Final packing step.
            """
            self.taskcount=self.taskcount+1
            input_dir=f"{str(self.taskcount-1)}_{self.previous_task}/out/packed"
            print(f"Task count is {self.taskcount}")
            taskname = "fastrelax"
            self.previous_task = taskname
            taskdir = f"{self.base_path}/{str(self.taskcount)}_{taskname}"
            os.makedirs(f"{taskdir}/in",exist_ok=True)
            os.makedirs(f"{taskdir}/out",exist_ok=True) 

            pdb_file=os.listdir(input_dir)[0]
            lig_file="ALR.params"
            pdb_path=f"{input_dir}/{pdb_file}"
            lig_path=f"{self.pipeline_inputs}/{lig_file}"
            output_dir=f"{taskdir}/out"

            return(
                f"python {self.scripts_path}/fastrelax.py "
                f"{pdb_path} "
                f"-n 1 "
                f"-lig {lig_path} "
                f"--out_dir {output_dir} "
            )

        #filter energy
        @self.auto_register_task()
        async def filter_energy(ligand_name:str = "ALR"):
#            self.taskcount=self.taskcount+1
            input_dir=f"{str(self.taskcount)}_{self.previous_task}/out"
            print(f"Task count is {self.taskcount}")
            taskname = "filter_energy"
#            self.previous_task = taskname
            taskdir = f"{self.base_path}/{str(self.taskcount)}_{taskname}"
            os.makedirs(f"{taskdir}/in",exist_ok=True)
            os.makedirs(f"{taskdir}/out",exist_ok=True) 

            pdb_directory = input_dir
            outputs_dir = f"{taskdir}/out"
            output_file = f"{outputs_dir}/negative_ligand_filenames.txt"
            output_energy_file = f"{outputs_dir}/negative_ligand_energies.txt"
            common_filenames_file = f"{self.pipeline_inputs}/common_filenames.txt"
            
            return(
                f"python {self.scripts_path}/filter_energy.py "
                f"{pdb_directory} "
                f"{output_file} "
                f"{output_energy_file} "
                f"{common_filenames_file} "
                f"{ligand_name} "
            )

        #filter shape
        @self.auto_register_task()
        async def filter_shape(ligand_name:str = "ALR"):
#            self.taskcount=self.taskcount+1
            input_dir=f"{str(self.taskcount)}_{self.previous_task}/out"
            print(f"Task count is {self.taskcount}")
            taskname = "filter_shape"
#            self.previous_task = taskname
            taskdir = f"{self.base_path}/{str(self.taskcount)}_{taskname}"
            os.makedirs(f"{taskdir}/in",exist_ok=True)
            os.makedirs(f"{taskdir}/out",exist_ok=True) 

            pdb_directory = input_dir
            SC_output_file = "shape_complementarity_values.txt"

            return(
                f"python {self.scripts_path}/filter_shape.py "
                f"{pdb_directory} "
                f"{taskdir}/out/{SC_output_file} "
                f"{self.pipeline_inputs}/{ligand_name} "
                f"{taskdir}/out/interface_values.txt "
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

            self.logger.pipeline_log("running lmpnn 1")
            await self.mpnn(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("lmpnn finished")

            self.logger.pipeline_log("running packmin 1")
            await self.packmin(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("packmin finished")

            self.logger.pipeline_log("running lmpnn 2")
            await self.mpnn(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("lmpnn finished")

            self.logger.pipeline_log("running packmin 2")
            await self.packmin(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("packmin finished")

            self.logger.pipeline_log("running lmpnn 3")
            await self.mpnn(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("lmpnn finished")

            self.logger.pipeline_log("running fastrelax")
            await self.fastrelax(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("fastrelax finished")

            self.logger.pipeline_log("running energy filter")
            await self.filter_energy(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("energy filter finished")

            self.logger.pipeline_log("running shape filter")
            await self.filter_shape(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("shape filter finished")

            await self.run_adaptive_step(wait=True)

            self.passes += 1

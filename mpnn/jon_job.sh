#!/bin/bash
NETID="ja961"
com2="squeue -u ${NETID} | wc -l"
check1=$(eval "$com2")
od="/home/ja961/Khare/pipeline/af_pipeline_outputs/af/"; for f in $od/fasta/*.fasta; do
jobname="$(basename $f .fasta)_af2_dimer";
com=$(cat << EOM
#SBATCH --gres=gpu:1
./af2_multimer_reduced.sh "${f}" "${od}/prediction/dimer_models"
EOM
)
python slurmit_BAY.py --job $jobname --partition gpu --tasks 8 --cpus 1 --mem 32G --time 4:00:00 --begin now --requeue True --outfiles $od/prediction/logs/${jobname}_%a --command "$com"
done
check2=$(eval "$com2")
while [ $check2 -gt $check1 ]; do\
    sleep 300
    check2=$(eval "$com2")
done
for i in ${od}/prediction/dimer_models/*; do fi="$(basename $i)"; cp $i/*ranked_0*.pdb ${od}/prediction/best_models/${fi}.pdb; done
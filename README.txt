af2_multimer_reduced.sh - Script for running AlphaFold-Multimer on reduced database mode.
af_check.py - Script for stitching together fasta files from ProteinMPNN output.
find_binders_af.py - Script for computing metrics on output structures from current iteration. Saves metrics to PDZ_bind_check_af.csv, which is read in by mpnn_af_pipeline.
jon_job.sh - Monitor script for submitting a series of AlphaFold-Multimer jobs. Job submission parameters (ie partition, cpus, job time, etc.) can be customized here.
mpnn_af_pipeline.py - Main script for pipeline. Calls all other scripts either directly or indirectly over the course of 5 passes of ProteinMPNN outputs to AlphaFold.
mpnn_wrapper.py - Python wrapper for ProteinMPNN, made for convenience. Makes customizing ProteinMPNN parameters much easier. (Should add that repo here as well)
slurmit_BAT.py - Python wrapper for slurm submission to cluster. Makes running multiple jobs in parallel on the cluster much easier.

mpnn_af_pipeline calls mpnn_wrapper, af_check, jon_job, and find_binders_af. This order of submission is maintained over 5 iterations. 
jon_job calls af2_multimer_reduced and slurmit_BAY to submit an alphafold job for every fasta file in a given directory. 

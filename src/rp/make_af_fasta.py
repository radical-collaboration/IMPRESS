from pyrosetta import *
init()
import os
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--name', type=str, help='structure name')
parser.add_argument('--out', type=str, help='pipeline name')
parser.add_argument('--seq',type=str, help='sequence')
args = parser.parse_args()

pep_seq='EGYQDYEPEA'

full_path='/home/ja961/Khare/pipeline/'

with open(full_path+'/af_pipeline_outputs_multi/'+args.out+'/af/fasta/'+args.name+'.fa','w') as f:
	f.write('>pdz\n')
	f.write(args.seq+'\n')
	f.write('>pep\n')
	f.write(pep_seq+'\n')
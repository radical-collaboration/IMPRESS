from pyrosetta import *
init()
import os
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-pdb", "--input_path", help="OG structure path", type=str)
parser.add_argument("-out", "--output_path", help="MPNN seq path", type=str)
parser.add_argument('-write_path', type=str)
args = parser.parse_args()
pep_seq='EGYQDYEPEA'
input_dir=args.input_path
output_dir=args.output_path
write_path=args.write_path
#output_dir="pdz_outputs/seqs/"
#input_dir="../inputs/resolved_structures/"
#rmsd_list=[]
#file_list=[]
def mk_fasta(receptor_seq, peptide_seq, filename, out):
    lines = [">receptor", receptor_seq, ">peptide", peptide_seq]
    with open('/home/ja961/Khare/pipeline/af_pipeline_outputs_multi/'+out+'/af/fasta/' + filename, "w") as f:
        f.write('\n'.join(lines))

for files in os.listdir(output_dir):
	print('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
	print(files)
	pose=pose_from_pdb(input_dir+files.split('.')[0]+'.pdb')
	if files[-2:]=='fa':
		filepath=output_dir+files
		file=open(filepath, 'r')
		lines=file.readlines()
		line_ctr=1
		og_seq=[]
		design_list=[]
		nr_design_list=[]
		fixed_chain_list=[]
		designed_chain_list=[]
		for line in lines:
			
			if line_ctr==1:
				fixed_start=line.find('fixed_chains')
				fixed_start+=12
				while line[fixed_start]!=']':
					if line[fixed_start].isalpha():
						fixed_chain_list.append(line[fixed_start])
					fixed_start+=1
				
				design_start=line.find('designed_chains')
				design_start+=15
				while line[design_start]!=']':
					if line[design_start].isalpha():
						designed_chain_list.append(line[design_start])
					design_start+=1


			elif line_ctr==2:
				temp_line=line.replace('\n','')
				temp_line=temp_line.split('/')
				
				for entries in temp_line:
					og_seq.append(entries)

			elif line_ctr%2==0:
				temp_list=[]
				temp_line=line.replace('\n','')
				temp_line=temp_line.split('/')
				for entries in temp_line:
					temp_list.append(entries)
				design_list.append(temp_list)
			line_ctr+=1
		#print(fixed_chain_list)
		#print(designed_chain_list)
		
		for chains in design_list:
			temp_nr=[]
			for seqs in chains:
				if seqs not in temp_nr:
					temp_nr.append(seqs)
			nr_design_list.append(temp_nr)
		print(nr_design_list)
		#print(files)
		#print(pose.num_chains())
		#print(og_seq)
		#print(nr_design_list)
		#construct full sequences
		designed_chain_list_num=[]
		fixed_chain_list_num=[]

		for i in designed_chain_list:
			designed_chain_list_num.append(ord(i)-64)
		for j in fixed_chain_list:
			fixed_chain_list_num.append(ord(j)-64)
		#print(fixed_chain_list_num)
		#print(fixed_chain_list)
		#print(designed_chain_list_num)
		#print(designed_chain_list)
		
		design_check_list=[]
		design_check=False
		bool_list=[]
		print(designed_chain_list_num)
		print(fixed_chain_list_num)
		iter_list=designed_chain_list_num+fixed_chain_list_num
		for k in iter_list:
			if k in designed_chain_list_num:
				design_check=True
			elif k in fixed_chain_list_num:
				design_check=False
			bool_list.append(design_check)
		index=1
		#print(pose.num_chains())
		#print(bool_list)
		tmp_list=[]
		for bools in bool_list:
			tmp_list.append(index)
			tmp_list.append(bools)
			design_check_list.append(tmp_list)
			index+=1
			tmp_list=[]
		
		print(design_check_list)
		full_og_seq=pose.sequence()
		full_designed_seqs=[]
		full_design_str=""
		#print(nr_design_list)
		design_ctr_1=0
		full_chain_list=[]
		#print(nr_design_list)
		for designs in nr_design_list:
			design_ctr_2=0
			for l, m in design_check_list:
				if m==True:
					full_chain_list.append(nr_design_list[design_ctr_1][design_ctr_2])
				else:
					full_chain_list.append(pose.chain_sequence(l))
				design_ctr_2+=1
			#print(full_chain_list)
			mk_fasta(full_chain_list[0], pep_seq, files.split('.')[0] + ".fa", write_path)
			full_chain_list=[]
			design_ctr_1+=1
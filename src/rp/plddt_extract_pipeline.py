from biopandas.pdb import PandasPdb
import os
import pandas as pd
import json
import operator
from pyrosetta import *
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--iter', type=str, help='pass iteration')
parser.add_argument('--out', type=str, help='pipeline name')
parser.add_argument('--path', type=str, help='base path')
#parser.add_argument('--seq',type=str, help='sequence')
args = parser.parse_args()



init()
filename=[]
plddt_list=[]
ptm_list=[]
pae_list=[]
ppdb=PandasPdb()


af_path=args.path+'af_pipeline_outputs_multi/'+args.out+'/af/prediction/'

def get_b_factor(pose, residue):
	""" 
	Given a pose and a residue number, will return the average b-factor of the 
	backbone atoms (N, CA, C) for the specified residue. Requires residue to  
	be input as a pose number, as opposed to a PDB number. 
	"""
	bfactor = pose.pdb_info().bfactor
	atom_index = pose.residue(residue).atom_index

	total_b = 0.0
	for atom in ['N', 'CA', 'C']:
		total_b += bfactor(residue, atom_index(atom))

	# Return average for three atoms
	return total_b / 3

#for jobs in os.listdir('PDZ_structures/'):
#	print(jobs)
for files in os.listdir(af_path+'best_models/'):
	print(files)
	full_path_pdb=af_path+'best_models/'+files
	full_path_ptm=af_path+'best_ptm/'
	pose=pose_from_pdb(full_path_pdb)
	temp_sum=0
	for i in range(len(pose.sequence())):
		temp_sum+=get_b_factor(pose,i+1)

	# ppdb.read_pdb(full_path_pdb)
	# temp_list=ppdb.df['ATOM']['b_factor']
	# counter = 0
	# temp_sum = 0
	# for entries in temp_list:
	# 	temp_sum+=entries
	# 	counter+=1
	if len(pose.sequence())>0:
		temp_avg=temp_sum/len(pose.sequence())
		filename.append(files)
		plddt_list.append(temp_avg)
		query=files.split('.')
		temp_max=0
		for jsons in os.listdir(full_path_ptm):
			hit = jsons.split('.')
			if query[0]==hit[0]:
				data = json.load(open(full_path_ptm+jsons))
				for keys, values in data.items():
					if keys == 'iptm+ptm':
						for keys2, values2 in values.items():
							if values2 > temp_max:
								temp_max=values2
						ptm_list.append(temp_max)
					elif keys == 'order':
						top_rank=values[0]
				
				
				#df_json=pd.json_normalize(data)
				#order=df_json['order']
				#ptm=df_json['iptm+ptm']
				break
		for folders in os.listdir(af_path+'/dimer_models/'):
			folder_name = files.split('.')[0]
			if folders==folder_name:
				for output in os.listdir(af_path+'/dimer_models/'+folders):
					#print(top_rank)
					top_rank_compare="result_"+top_rank+".pkl"
					#print("$$$$$$$$$$$$$$$$$$$$")
					#print(top_rank_compare)
					#print(output)
					#print("$$$$$$$$$$$$$$$$$$$$")
					if output == top_rank_compare:
						details = pd.read_pickle(af_path+'/dimer_models/'+folders+'/'+output)
						#print(details)
						for keys3, values3 in details.items():
							if keys3=='predicted_aligned_error':
								length=values3.shape[0]
								running_sum=0
								counter2=0
								row_index=0
								target_range=range(length-10,length)
								for a in values3:
									col_index=0
									for b in a:
										#print(str(row_index) +','+str(col_index))
										#if row_index in target_range and col_index in target_range:
										#print("do nothing")
										if operator.xor(row_index in target_range, col_index in target_range):
											#print("adding")
											running_sum+=values3[row_index][col_index]
											counter2+=1
										col_index+=1
									row_index+=1
								avg_pae=running_sum/counter2
								pae_list.append(avg_pae)
print(len(filename))
print(len(plddt_list))
print(len(ptm_list))
print(len(pae_list))
final=tuple(zip(filename, plddt_list, ptm_list, pae_list))
#print(final)
df=pd.DataFrame(final, columns = ['ID', 'avg_plddt', 'ptm', 'avg_pae'])
#print(df)	
df.to_csv('af_stats_'+args.out+'_pass_'+args.iter+'.csv', index=False)

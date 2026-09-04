import argparse
import os
import re
import pyrosetta


def parse_args():
    parser = argparse.ArgumentParser(description="Rosetta shape-complementarity/interface analysis")
    parser.add_argument("pdb_directory",   help="Directory of PDB files to analyse")
    parser.add_argument("SC_output_file",  help="Output file for shape-complementarity values")
    parser.add_argument("ligand_name",     help="Ligand residue name (e.g. ALR)")
    parser.add_argument("gen_output_file", help="Output CSV for interface metrics")
    return parser.parse_args()


def main():
    args = parse_args()

    pyrosetta.init(
        f"-ignore_unrecognized_res -ignore_zero_occupancy --extra_res_fa {args.ligand_name}.params"
        f" -corrections::beta_nov16 true -mute all"
    )

    # Set up the general output file which will have metrics that look at the interface
    with open(args.gen_output_file, 'w') as genout:
        genout.write(
            "FileName,Shape Complementarity,ddg,contact molecular surf,SASA,"
            "Very buried unsat hbond,Surface unsat hbond,SAP SCORE\n"
        )

    # Create list of PDB files to analyze
    pdb_files = [f for f in os.listdir(args.pdb_directory) if f.endswith('.pdb')]

    protocol = pyrosetta.rosetta.protocols.rosetta_scripts.XmlObjects().create_from_string(
"""
<ROSETTASCRIPTS>
    <SCOREFXNS>
        <ScoreFunction name="sfxn_clean" weights="beta_nov16" />
    </SCOREFXNS>

    <RESIDUE_SELECTORS>
        <Chain name="chainA" chains="A" />
        <Chain name="chainB" chains="B" />
        <ScoreTermValueBased name="clashing_res" score_type="fa_rep" score_fxn="sfxn_clean"  lower_threshold="3" upper_threshold="99999" />


    </RESIDUE_SELECTORS>
    <TASKOPERATIONS>
        <IncludeCurrent name="ic" /> //includes input pdbs rotamers
        <LimitAromaChi2 name="limitaro" chi2max="110" chi2min="70" include_trp="1" /> //disallow extreme aromatic rotamers
        <ExtraRotamersGeneric name="ex1_ex2" ex1="1" ex2="1" /> //use ex1 ex2 rotamers
        <RestrictToRepacking name="repack_only" />  //for minimize/repack
    </TASKOPERATIONS>

    <FILTERS>
        <NetCharge name="chargeA" chain="1" confidence="0" />
        <ShapeComplementarity name="sc2" min_sc="0.6" verbose="1" quick="0" residue_selector1="chainA" residue_selector2="chainB" write_int_area="1" write_median_dist="1" confidence="0" />
        <ExposedHydrophobics name="exposed_hydrop" sasa_cutoff="20" threshold="0" confidence="0"/>
        <ContactMolecularSurface name="cms" distance_weight="0.5" use_rosetta_radii="true" apolar_target="0"
        target_selector="chainA" binder_selector="chainB" confidence="0" />

        <BuriedUnsatHbonds name="vbuns"  report_all_heavy_atom_unsats="true" scorefxn="sfxn_clean" ignore_surface_res="false" print_out_info_to_pdb="true" atomic_depth_selection="5" burial_cutoff="1000" residue_surface_cutoff="42.5" dalphaball_sasa="0" confidence="0"  only_interface="false"  />
	    	<BuriedUnsatHbonds name="sbuns" report_all_heavy_atom_unsats="true" scorefxn="sfxn_clean" cutoff="4" residue_surface_cutoff="42.5" ignore_surface_res="false" print_out_info_to_pdb="true" dalphaball_sasa="0" probe_radius="1.1" atomic_depth_selection="5.5" atomic_depth_deeper_than="false" only_interface="false" confidence="0" />
    </FILTERS>

    <MOVERS>

        <MinMover name="minimize_sc_all" scorefxn="sfxn_clean" bb="0" chi="1" />
        <InterfaceAnalyzerMover name="analyze_interface" scorefxn="sfxn_clean"
        packstat="1" interface_sc="1" use_jobname="1"
        jump="1" scorefile_reporting_prefix="IA" />

        <ddG name="ddG_no_repack" translate_by="1000" scorefxn="sfxn_clean" task_operations="repack_only,ic,ex1_ex2" relax_mover="minimize_sc_all"
            repack_bound="0"
            relax_bound="0"
            repack_unbound="0"
            relax_unbound="1"
        jump="1"
        dump_pdbs="0"   />
    </MOVERS>
    <SIMPLE_METRICS>
        <SapScoreMetric name="sap_score" />
        <SelectedResiduesPyMOLMetric name="clashing_res" residue_selector="clashing_res" custom_type="clashing_res" />
    </SIMPLE_METRICS>
    <PROTOCOLS>
        <Add mover="minimize_sc_all" />
        <Add mover="analyze_interface" />
        <Add mover="ddG_no_repack" />
        <Add filter="chargeA" />
        <Add filter="exposed_hydrop" />
        <Add filter="cms" />
        <Add filter="vbuns" />
        <Add filter="sbuns" />
        <Add metrics="sap_score" />
        <Add metrics="clashing_res" />

        <Add filter="sc2" />
    </PROTOCOLS>
</ROSETTASCRIPTS>

""").get_mover("ParsedProtocol")

    # Analyze the selected PDB files
    for pdb_file in pdb_files:
        full_path = os.path.join(args.pdb_directory, pdb_file)

        pose = pyrosetta.pose_from_pdb(full_path)
        protocol.apply(pose)

        with open(args.SC_output_file, 'a') as SCout:
            SCout.write(f"{pdb_file}\tShape Complementarity: {pose.scores['sc2']}\n")

        with open(args.gen_output_file, 'a') as genout:
            genout.write(
                f"{pdb_file},{pose.scores['sc2']},{pose.scores['ddg']},"
                f"{pose.scores['cms']},{pose.scores['IA_dSASA_int']},"
                f"{pose.scores['vbuns']},{pose.scores['sbuns']},{pose.scores['sap_score']}\n"
            )

    print(f"Shape complementarity values have been written to {args.SC_output_file}.")


if __name__ == "__main__":
    main()

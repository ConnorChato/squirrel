#!/usr/bin/env python3
from squirrel.utils.log_colours import green,cyan

import squirrel.utils.custom_logger as custom_logger
from squirrel.utils.config import *
from squirrel.utils.initialising import *
import squirrel.utils.io_parsing as io
import squirrel.utils.cns_qc as qc
import squirrel.utils.reconstruction_functions as recon
from squirrel.utils.make_report import *

import squirrel.utils.misc as misc
from squirrel import __version__
from . import _program

import os
import sys
import argparse
import snakemake

thisdir = os.path.abspath(os.path.dirname(__file__))
cwd = os.getcwd()


def main(sysargs = sys.argv[1:]):
    parser = argparse.ArgumentParser(prog = _program,
    description='squirrel: Some QUIck Rearranging to Resolve Evolutionary Links',
    usage='''squirrel <input> [options]''')

    io_group = parser.add_argument_group('Input-Output options')
    io_group.add_argument('input', nargs="*", help='Input fasta file of sequences to analyse.')
    io_group.add_argument('-o','--outdir', action="store",help="Output directory. Default: current working directory")
    io_group.add_argument('--outfile', action="store",help="Optional output file name. Default: <input>.aln.fasta")
    io_group.add_argument('--tempdir',action="store",help="Specify where you want the temp stuff to go. Default: $TMPDIR")
    io_group.add_argument("--no-temp",action="store_true",help="Output all intermediate files, for dev purposes.")

    a_group = parser.add_argument_group("Pipeline options")
    a_group.add_argument("-qc","--seq-qc",action="store_true",help="Flag potentially problematic SNPs and sequences. Note that this will also run phylo mode, so you will need to specify both outgroup sequences and provide an assembly reference file. Default: don't run QC")
    a_group.add_argument("--assembly-refs",action="store",help="References to check for `calls to reference` against.")
    a_group.add_argument("--no-mask",action="store_true",help="Skip masking of repetitive regions. Default: masks repeat regions")
    a_group.add_argument("--no-itr-mask",action="store_true",help="Skip masking of end ITR. Default: masks ITR")
    a_group.add_argument("--additional-mask",action="store",help="Masking additional sites provided.")
    a_group.add_argument("--extract-cds",action="store_true",help="Extract coding sequences based on coordinates in the reference")
    a_group.add_argument("--concatenate",action="store_true",help="Concatenate coding sequences for each genome, separated by `NNN`. Default: write out as separate records")
    a_group.add_argument("--clade",action="store",help="Specify whether the alignment is primarily for `cladei` or `cladeii` (can also specify a or b, e.g. `cladeia`, `cladeiib`). This will determine reference used for alignment, mask file and background set used if `--include-background` flag used in conjunction with the `--run-phylo` option. Default: `cladeii`")
    a_group.add_argument("-p","--run-phylo",action="store_true",help="Run phylogenetics pipeline")
    a_group.add_argument("-a","--run-apobec3-phylo",action="store_true",help="Run phylogenetics & APOBEC3-mutation reconstruction pipeline")
    a_group.add_argument("--outgroups",action="store",help="Specify which MPXV outgroup(s) in the alignment to use in the phylogeny. These will get pruned out from the final tree.")
    a_group.add_argument("-bg","--include-background",action="store_true",help="Include a default background set of sequences for the phylogenetics pipeline. The set will be determined by the `--clade` specified.")
    a_group.add_argument("-bf","--background-file",action="store",help="Include this additional FASTA file as background to the phylogenetics.")

    m_group = parser.add_argument_group('Misc options')
    m_group.add_argument("-v","--version", action='version', version=f"squirrel {__version__}")
    m_group.add_argument("--verbose",action="store_true",help="Print lots of stuff to screen")
    m_group.add_argument("-t","--threads",action="store",default=1,type=int, help="Number of threads")


    if len(sysargs)<1:
        parser.print_help()
        sys.exit(-1)
    else:
        args = parser.parse_args(sysargs)

    # Initialise config dict
    config = setup_config_dict(cwd)
    
    if args.clade:
        config[KEY_CLADE] = args.clade

    config["version"] = __version__
    get_datafiles(config)
    io.set_up_threads(args.threads,config)
    config[KEY_OUTDIR] = io.set_up_outdir(args.outdir,cwd,config[KEY_OUTDIR])
    config[KEY_OUTFILE],config[KEY_CDS_OUTFILE],config[KEY_OUTFILENAME],config[KEY_OUTFILE_STEM] = io.set_up_outfile(args.outfile,args.input, config[KEY_OUTFILE],config[KEY_OUTDIR])
    io.set_up_tempdir(args.tempdir,args.no_temp,cwd,config[KEY_OUTDIR], config)

    io.pipeline_options(args.no_mask, args.no_itr_mask, args.additional_mask, args.extract_cds, args.concatenate,cwd, config)

    config[KEY_INPUT_FASTA] = io.find_query_file(cwd, config[KEY_TEMPDIR], args.input)
    
    if args.background_file:
        config[KEY_INPUT_FASTA] = io.find_background_file(cwd,config[KEY_INPUT_FASTA],args.background_file,config)

    if args.seq_qc:
        print(green("QC mode activated. Squirrel will flag:"))
        print("- Clumps of unique SNPs\n- SNPs adjacent to Ns")
        config[KEY_SEQ_QC] = True
    
    assembly_refs = []
    if args.seq_qc and args.run_phylo:
        print("- Reversions to reference\n- Convergent mutations")
        assembly_refs = qc.find_assembly_refs(cwd,args.assembly_refs,config)
        # args.run_phylo = True

    config[KEY_FIG_HEIGHT] = recon.get_fig_height(config[KEY_INPUT_FASTA])
    config[KEY_INPUT_FASTA] = io.phylo_options(args.run_phylo,args.run_apobec3_phylo,args.outgroups,args.include_background,config[KEY_INPUT_FASTA],config)

    snakefile = get_snakefile(thisdir,"msa")

    status = misc.run_snakemake(config,snakefile,args.verbose,config)


    if status:

        if config[KEY_RUN_PHYLO]:
            phylo_snakefile = get_snakefile(thisdir,"phylo")
            phylo_stem = ".".join(config[KEY_OUTFILENAME].split(".")[:-1])
            phylo_stem=phylo_stem.split("/")[-1]
            config[KEY_PHYLOGENY] = f"{phylo_stem}.tree"
            
            config[KEY_OUTGROUP_STRING] = ",".join(config[KEY_OUTGROUPS])
            config[KEY_OUTGROUP_SENTENCE] = " ".join(config[KEY_OUTGROUPS])

            if config[KEY_RUN_APOBEC3_PHYLO]:
                config[KEY_PHYLOGENY_SVG] = f"{phylo_stem}.tree.svg"
                phylo_snakefile = get_snakefile(thisdir,"reconstruction")

            status = misc.run_snakemake(config,phylo_snakefile,args.verbose,config)

            if status:
                if config[KEY_RUN_APOBEC3_PHYLO]:
                    print(green("Ancestral reconstruction & phylogenetics complete."))
                else:
                    print(green("Phylogenetics complete."))

        if args.seq_qc:
            mask_file = qc.check_for_snp_anomalies(assembly_refs,config,config[KEY_FIG_HEIGHT])
            print(green("Flagged mutations writted to:"), f"{mask_file}")
        else:
            print(green("Alignment complete."))
            mask_file = ""
        # get the inputs for making the overall report
        report =os.path.join(config[KEY_OUTDIR],"squirrel-report.html")
        make_output_report(report,mask_file,config)

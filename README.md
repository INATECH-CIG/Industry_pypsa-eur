# Industry_optimisation_model
Optimisation model of German energy-intensive industry sector built with PyPSA framework. Can be attached to a PyPSA-Eur model for coupled optimisation with the energy system, or optimised independently. 

scripts:
----------------
main: Builds industry optimization model and solves it independently (soft-linked) or co-optimized with a PyPSA-Eur network (coupled). Takes data from the folder data and functions from industry_model and industry_input. If you want to run the code, set coupling degree: 
A. co-optimization: set "coupled", 
B. soft-link: set 1. "esm_only", 
                  2. "industry_only", 
                  3. "esm_softlinked"

and run the file. The current code only test-solves the optimization for the first 6 timesteps; to completely solve the network, set solve_industry_module(..snapshots = n.snapshots).

main_variations: scenario variations for energy carrier prices and sectoral resource shares.

scripts_preprocessing: 
---------------------------
contains scripts that pre-process raw data. The folder data already contains the pre-processed data, so these scripts do not need to be run. 

data:
---------------------------
contains all needed processed and raw data and PyPSA-Eur networks.

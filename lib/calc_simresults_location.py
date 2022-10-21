#!/usr/bin/env python
"""Utility functions to calculate the location of simresults directories."""
import getpass
import os
import re

SIMRESULTS = os.environ['SIMRESULTS']


def calc_simresults_location(checkout_path):
    """Calculate the path to put regression results."""
    username = getpass.getuser()

    # FIXME, we may want to detect who owns the check to allow for rerunning in someone else's area? # pylint: disable=fixme
    sim_results_home = os.path.join(SIMRESULTS, username)
    if not os.path.exists(sim_results_home):
        os.mkdir(sim_results_home)

    # If username is in the checkout_path try to reduce the name
    # Assume username is somewhere is path
    try:
        checkout_path = re.search("{}/(.*)".format(username), checkout_path).group(1)
    except AttributeError:
        pass
    checkout_path = checkout_path.replace('/', '_')
    # Adding the datetime into the regression directory will force a recompile.
    # Ideally, the vcomp directory will need to have the same name
    # strdate = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(time.time()))
    # regression_directory = '{}__{}'.format(checkout_path, strdate)
    regression_directory = checkout_path
    regression_directory = os.path.join(sim_results_home, regression_directory)
    return regression_directory


if __name__ == "__main__":
    PROJ_DIR = os.environ['PROJ_DIR']
    print(calc_simresults_location(PROJ_DIR))

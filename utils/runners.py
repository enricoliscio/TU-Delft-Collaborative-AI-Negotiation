from itertools import permutations
from typing import Tuple

from geniusweb.profile.utilityspace.LinearAdditiveUtilitySpace import (
    LinearAdditiveUtilitySpace,
)
from geniusweb.profileconnection.ProfileConnectionFactory import (
    ProfileConnectionFactory,
)
from geniusweb.protocol.NegoSettings import NegoSettings
from geniusweb.protocol.session.saop.SAOPState import SAOPState
from geniusweb.simplerunner.ClassPathConnectionFactory import ClassPathConnectionFactory
from geniusweb.simplerunner.NegoRunner import NegoRunner
from pyson.ObjectMapper import ObjectMapper
from uri.uri import URI

from utils.std_out_reporter import StdOutReporter


def run_session(settings) -> Tuple[dict, dict]:
    agents = settings["agents"]
    profiles = settings["profiles"]
    rounds = settings["deadline_rounds"]

    # quick and dirty checks
    assert isinstance(agents, list) and len(agents) == 2
    assert isinstance(profiles, list) and len(profiles) == 2
    assert isinstance(rounds, int) and rounds > 0

    # file path to uri
    profiles_uri = [f"file:{x}" for x in profiles]

    # create full settings dictionary that geniusweb requires
    settings_full = {
        "SAOPSettings": {
            "participants": [
                {
                    "TeamInfo": {
                        "parties": [
                            {
                                "party": {
                                    "partyref": f"pythonpath:{agents[0]}",
                                    "parameters": {},
                                },
                                "profile": profiles_uri[0],
                            }
                        ]
                    }
                },
                {
                    "TeamInfo": {
                        "parties": [
                            {
                                "party": {
                                    "partyref": f"pythonpath:{agents[1]}",
                                    "parameters": {},
                                },
                                "profile": profiles_uri[1],
                            }
                        ]
                    }
                },
            ],
            "deadline": {"DeadlineRounds": {"rounds": rounds, "durationms": 999}},
        }
    }

    # parse settings dict to settings object
    settings_obj = ObjectMapper().parse(settings_full, NegoSettings)

    # create the negotiation session runner object
    runner = NegoRunner(settings_obj, ClassPathConnectionFactory(), StdOutReporter(), 0)

    # run the negotiation session
    runner.run()

    # get results from the session in class format and dict format
    results_class: SAOPState = runner.getProtocol().getState()
    results_dict = ObjectMapper().toJson(results_class)

    # add utilities to the results and create a summary
    results_trace, results_summary = process_results(results_class, results_dict)

    return results_trace, results_summary


def run_tournament(tournament_settings: dict) -> Tuple[list, list]:
    # create agent permutations, ensures that every agent plays against every other agent on both sides of a profile set.
    agent_permutations = permutations(tournament_settings["agents"], 2)
    profile_sets = tournament_settings["profile_sets"]
    deadline_rounds = tournament_settings["deadline_rounds"]

    results_summaries = []
    tournament = []
    for profiles in profile_sets:
        # quick an dirty check
        assert isinstance(profiles, list) and len(profiles) == 2
        for agent_duo in agent_permutations:
            # create session settings dict
            settings = {
                "agents": list(agent_duo),
                "profiles": profiles,
                "deadline_rounds": deadline_rounds,
            }

            # run a single negotiation session
            _, results_summary = run_session(settings)

            # assemble results
            tournament.append(settings)
            results_summaries.append(results_summary)

    return tournament, results_summaries


def process_results(results_class, results_dict):
    results_dict = results_dict["SAOPState"]

    # dict to translate geniusweb agent reference to Python class name
    agent_translate = {
        k: v["party"]["partyref"].split(".")[-1]
        for k, v in results_dict["partyprofiles"].items()
    }

    results_summary = {}

    # check if there are any actions (could have crashed)
    if results_dict["actions"]:
        # obtain utility functions
        utility_funcs = {
            k: get_utility_function(v["profile"])
            for k, v in results_dict["partyprofiles"].items()
        }

        # iterate both action classes and dict entries
        actions_iter = zip(results_class.getActions(), results_dict["actions"])

        for num_offer, (action_class, action_dict) in enumerate(actions_iter):
            if "Offer" in action_dict:
                offer = action_dict["Offer"]
            elif "Accept" in action_dict:
                offer = action_dict["Accept"]
            else:
                continue

            # add utility of both agents
            bid = action_class.getBid()
            offer["utilities"] = {
                k: float(v.getUtility(bid)) for k, v in utility_funcs.items()
            }

        results_summary["num_offers"] = num_offer + 1

        # gather a summary of results
        if "Accept" in action_dict:
            for actor, utility in offer["utilities"].items():
                position = actor.split("_")[-1]
                results_summary[f"agent_{position}"] = agent_translate[actor]
                results_summary[f"utility_{position}"] = utility
            util_1, util_2 = offer["utilities"].values()
            results_summary["nash_product"] = util_1 * util_2
            results_summary["social_welfare"] = util_1 + util_2
            results_summary["result"] = "agreement"
        else:
            for actor, utility in offer["utilities"].items():
                position = actor.split("_")[-1]
                results_summary[f"agent_{position}"] = agent_translate[actor]
                results_summary[f"utility_{position}"] = 0
            results_summary["nash_product"] = 0
            results_summary["social_welfare"] = 0
    else:
        # something crashed crashed
        for actor in results_dict["connections"]:
            position = actor.split("_")[-1]
            results_summary[f"agent_{position}"] = agent_translate[actor]
            results_summary[f"utility_{position}"] = 0
        results_summary["nash_product"] = 0
        results_summary["social_welfare"] = 0
        results_summary["result"] = "ERROR"

    return results_dict, results_summary


def get_utility_function(profile_uri) -> LinearAdditiveUtilitySpace:
    profile_connection = ProfileConnectionFactory.create(
        URI(profile_uri), StdOutReporter()
    )
    profile = profile_connection.getProfile()
    assert isinstance(profile, LinearAdditiveUtilitySpace)

    return profile

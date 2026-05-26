sections__calendar = {
    "meterLink_google_keep": {
        "Preset": "InjectedByTest",
    },
    "meterLink_google_calendar": {
        "Preset": "InjectedByTest",
    },
}


sections__oanda = {
    "meterLink_broker": {
        "Preset": "InjectedByTest",
    },
    "meterLink_news": {
        "Preset": "InjectedByTest" # values must be strings
    },
    "meterLink_metrics": {
        "Preset": "InjectedByTest"# values must be strings
    }
}


sections__check_desktop = {
    "meterLink_github": {
        "Preset": "InjectedByTest",
    },
    "meterLink_dump": {
        "Preset": "InjectedByTest",
    },
}


sections__check_world_checks = {
    "meterLink_github": {
        "Preset": "InjectedByTest",
    },
}


sections__check_logs = {
    "meterLink_elastic": {
        "Preset": "InjectedByTest",
    },
    "meterLink_schedule": {
        "Preset": "InjectedByTest",
    },
}


sections__tcg_mp_sections = {
    "meterLink_orders": {
        "Preset": "InjectedByTest",
    },
    "meterLink_sales": {
        "Preset": "InjectedByTest" # values must be strings
    },
    "meterLink_metrics": {
        "Preset": "InjectedByTest"# values must be strings
    },
    "meterLink_audit": {
        "Preset": "InjectedByTest"  # values must be strings
    },
    "meterLink_sc": {
        "Preset": "InjectedByTest"  # values must be strings
    },


}


sections__tcg_mp_sell_cart_sections = {
    # `meterLink` (the template default) is used for SELL CART;
    # `meterLink_dump` is the second top-row slot, opening the dump.txt file
    # produced by Rainmeter on every run. See `show_tcg_sell_cart`.
    "meterLink_dump": {
        "Preset": "InjectedByTest",
    },
}


sections__utilities_desktop = {
    "meterLink_home": {
        "Preset": "InjectedByTest",
    },
    "meterLink_home_save": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_home": {
        "Preset": "InjectedByTest",
    },

    "meterLink_office": {
        "Preset": "InjectedByTest",
    },
    "meterLink_office_save": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_office": {
        "Preset": "InjectedByTest",
    },

    "meterLink_custom": {
        "Preset": "InjectedByTest",
    },
    "meterLink_custom_save": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_custom": {
        "Preset": "InjectedByTest",
    },
}

sections__utilities_ai = {
    "meterSeperator_n8n": {
        "Preset": "InjectedByTest",
    },

    "meterLink_agent_chat": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_agent_chat": {
        "Preset": "InjectedByTest",
    },

    "meterLink_agent_chat_tests": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_agent_chat_tests": {
        "Preset": "InjectedByTest",
    },

    "meterLink_agent_voice": {
        "Preset": "InjectedByTest",
    },
    "meterSeperator_agent_voice": {
        "Preset": "InjectedByTest",
    },
}


sections__utilities_i_cue = {
    "meterLink_dump": {
        "Preset": "InjectedByTest",
    },
}

sections__ynab = {
    "meterLink_php": {
        "Preset": "InjectedByTest",
    },
}


sections__pc_daily_sales = {
    # Only the template default `meterLink` is used — carries the WEB link
    # to the AppSheet app. No additional top-row slots.
}


sections__api_costs = {
    # `meterLink` (template default) carries ANTHROPIC; the rest are extras
    # positioned dynamically via `compute_horizontal_link_layout` in
    # show_api_costs (X / W coords come from label widths, not hardcoded).
    "meterLink_openai": {
        "Preset": "InjectedByTest",
    },
    "meterLink_gemini": {
        "Preset": "InjectedByTest",
    },
}

sections__utilities_ahk = {}


sections__sensors = {
    # Only the template default `meterLink` is used — carries KIBANA, opening
    # the dev console for the harqis-sensor-telemetry index. No extra top-row
    # slots (mirrors sections__daily_radar).
}


sections__daily_radar = {
    # Only the template default `meterLink` is used — carries DUMP, opening
    # the rendered dump.txt for the DAILY RADAR widget. No additional
    # top-row slots (per requirement: "only one link for the DUMP text").
}


sections__jira_board = {
    # Header link slots — `meterLink` (template default) carries JIRA_BOARD;
    # the rest are positioned dynamically via `compute_horizontal_link_layout`
    # in `show_jira_board` (X coords come from label widths, not hardcoded).
    "meterLink_dump": {
        "Preset": "InjectedByTest",
    },
    "meterLink_dashboard": {
        "Preset": "InjectedByTest",
    },
    "meterLink_repository": {
        "Preset": "InjectedByTest",
    },
    "meterLink_structure": {
        "Preset": "InjectedByTest",
    },
}


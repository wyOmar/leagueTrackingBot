def get_rank_value(rank_str: str, lp: int) -> int:
    """Helper to calculate a numeric value for sorting ranks."""
    if not rank_str or rank_str == "Unranked":
        return -1
    tier_values = {
        "Iron": 0, "Bronze": 400, "Silver": 800, "Gold": 1200, 
        "Platinum": 1600, "Emerald": 2000, "Diamond": 2400, 
        "Master": 2800, "Grandmaster": 3200, "Challenger": 3600
    }
    div_values = {"IV": 0, "III": 100, "II": 200, "I": 300}
    
    parts = rank_str.split()
    tier = parts[0]
    div = parts[1] if len(parts) > 1 else "IV"
    return tier_values.get(tier, 0) + div_values.get(div, 0) + lp

def format_rank_string(rank_str: str, lp: int, emoji_map: dict, include_lp_for_non_apex: bool = False) -> str:
    """
    Standardizes rank formatting across the bot.
    Apex tiers (Master+) always show LP. Standard tiers optionally show LP based on the context.
    """
    if not rank_str or rank_str == "Unranked":
        return "Unranked"

    parts = rank_str.split()
    tier = parts[0]
    rank_emoji = emoji_map.get(tier, tier)
    
    apex_tiers = ["Master", "Grandmaster", "Challenger"]
    division_map = {"I": "𝐈", "II": "𝐈𝐈", "III": "𝐈𝐈𝐈", "IV": "𝐈𝐕"}
    
    if tier in apex_tiers:
        return f"{rank_emoji} {lp}LP"
    else:
        div = parts[1] if len(parts) > 1 else ""
        fancy_div = division_map.get(div, div)
        if include_lp_for_non_apex:
            return f"{rank_emoji} {fancy_div} — {lp}LP"
        return f"{rank_emoji} {fancy_div}"
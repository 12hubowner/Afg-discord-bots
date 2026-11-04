-- LRM runtime vars
LRM_IsUserPremium = true
LRM_SecondsLeft = 12345
LRM_LinkedDiscordID = "<discord_id>"
LRM_ScriptName = "keyhub"
-- end LRM

-- your actual hub goes here
-- LRM_IsUserPremium, LRM_SecondsLeft, LRM_LinkedDiscordID injected above

print("[keyhub] authorized as discord id " .. tostring(LRM_LinkedDiscordID))
print("[keyhub] seconds left: " .. tostring(LRM_SecondsLeft))

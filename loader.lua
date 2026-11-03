-- keyhub loader — paste into Delta Executor
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local player = Players.LocalPlayer

local API_URL = "https://afg-discord-bots.onrender.com/load"
local API_SECRET = "keyhub_9f3a8c7e2b1d4056_do_not_share"

local function get_hwid()
    return (syn and syn.get_hwid and syn.get_hwid())
        or (gethwid and gethwid())
        or (get_hwid and get_hwid())
        or "UNKNOWN"
end

local function http_post(url, body)
    local req = (syn and syn.request) or (http and http.request) or http_request or request
    if not req then return nil, "executor has no http request" end
    local ok, res = pcall(function()
        return req({
            Url = url,
            Method = "POST",
            Headers = { ["Content-Type"] = "application/json" },
            Body = HttpService:JSONEncode(body),
        })
    end)
    if not ok then return nil, tostring(res) end
    return res
end

local hwid = get_hwid()

-- Initial verification
local res, err = http_post(API_URL, {
    secret = API_SECRET,
    key = script_key or "",
    hwid = hwid,
})

if not res then
    warn("[keyhub] network error: " .. tostring(err))
    return
end

local ok, data = pcall(function() return HttpService:JSONDecode(res.Body) end)
if not ok or not data then
    warn("[keyhub] bad response")
    return
end

if not data.ok then
    if data.error == "paused" then
        player:Kick("The script is currently PAUSED by the owner for maintenance. Your timer has been stopped.")
        return
    end
    warn("[keyhub] auth failed: " .. tostring(data.error))
    return
end

-- Run the actual script
local chunk, load_err = loadstring(data.script)
if not chunk then
    warn("[keyhub] script load failed: " .. tostring(load_err))
    return
end

chunk()

-- ==========================================
-- HEARTBEAT LOOP (Checks every 5s if paused)
-- ==========================================
task.spawn(function()
    while true do
        task.wait(5)
        
        local hb_res = http_post(API_URL, {
            secret = API_SECRET,
            key = script_key or "",
            hwid = hwid,
        })
        
        if hb_res and hb_res.Body then
            local hb_ok, hb_data = pcall(function() return HttpService:JSONDecode(hb_res.Body) end)
            if hb_ok and hb_data then
                if hb_data.error == "paused" then
                    -- Kick the user immediately
                    player:Kick("⚠️ SCRIPT PAUSED ⚠️\n\nThe owner has paused the script. Your timer is frozen and will resume when logs return.")
                    break
                elseif hb_data.error == "expired" or hb_data.error == "invalid_key" or hb_data.error == "hwid_mismatch" then
                    player:Kick("⚠️ AUTH ERROR ⚠️\n\nYour key is no longer valid: " .. tostring(hb_data.error))
                    break
                end
            end
        end
    end
end)

--[[
    Afg Joiner - STEAL A BRAINROT - Roblox Script
    Features: Auto Join, Blacklist, Firebase Integration, GUI
    Theme: Red Neon
    DISPLAY: Name | Value | JOIN Button
    NO LAG - OPTIMIZED
]]

-- ============================================================================
-- SAFE LOAD WRAPPER (iterative retry - no stack growth)
-- ============================================================================
local function safeLoad()
    local attempt = 0
    while true do
        attempt = attempt + 1
        local success, err = pcall(function()
            print("[Afg Joiner] Initializing (attempt " .. attempt .. ")...")

            local Players          = game:GetService("Players")
            local HttpService      = game:GetService("HttpService")
            local TeleportService  = game:GetService("TeleportService")
            local CoreGui          = game:GetService("CoreGui")
            local UserInputService = game:GetService("UserInputService")
            local RunService       = game:GetService("RunService")
            local PlayerGui        = Players.LocalPlayer:WaitForChild("PlayerGui")

            local Player = Players.LocalPlayer

            -- ===================== CONFIGURATION =====================
            local FIREBASE_URL  = "https://afg-ajws-default-rtdb.firebaseio.com/.json"
            local POLL_INTERVAL = 1.5
            local MIN_VAL       = 10000000

            local AJ_DELAY      = 5
            local JOIN_COOLDOWN = 1.5
            local MAX_ROWS      = 100
            local PROCESSED_TTL = 600

            local isProcessing  = false
            local joinQueue     = {}

            local processedIds = {}

            -- ============================================================================
            -- MOBILE / PC DETECTION & SCALING
            -- ============================================================================
            local isMobile = UserInputService.TouchEnabled and not UserInputService.MouseEnabled
            local SCALE    = isMobile and 0.65 or 1.0
            local GUI_WIDTH  = isMobile and 320 or 450
            local GUI_HEIGHT = isMobile and 380 or 420
            local FONT_SIZE_MULTIPLIER = isMobile and 0.8 or 1.0
            local ROW_HEIGHT       = isMobile and 40 or 48
            local HEADER_HEIGHT    = isMobile and 85 or 105
            local CONTROLS_HEIGHT  = isMobile and 28 or 32
            local DISCORD_HEIGHT   = isMobile and 28 or 32
            local TOGGLE_SIZE      = isMobile and 40 or 45

            -- ============================================================================
            -- UI THEME
            -- ============================================================================
            local THEME = {
                Background    = Color3.fromRGB(10, 10, 10),
                SidebarBG     = Color3.fromRGB(18, 18, 18),
                ItemBG        = Color3.fromRGB(30, 30, 30),
                Stroke        = Color3.fromRGB(74, 74, 74),
                Accent        = Color3.fromRGB(255, 50, 50),
                DiscordAccent = Color3.fromRGB(255, 50, 50),
                TextWhite     = Color3.fromRGB(246, 246, 246),
                TextGray      = Color3.fromRGB(170, 170, 170),
                GreenActive   = Color3.fromRGB(52, 211, 153),
                RedSoft       = Color3.fromRGB(255, 120, 120),
            }

            local State = {
                AutoJoin     = false,
                MinGenFilter = MIN_VAL,
                BlackList    = {},
                ActiveTab    = "MONITOR",
            }

            -- ============================================================================
            -- HTTP REQUEST
            -- ============================================================================
            local function httpRequest(url)
                local reqFunc = (syn and syn.request) or http_request or request
                local body

                if reqFunc then
                    local ok, res = pcall(function()
                        return reqFunc({ Url = url, Method = "GET" })
                    end)
                    if ok and res and res.Body then
                        body = res.Body
                    end
                end

                if not body then
                    local ok, res = pcall(function()
                        return game:HttpGet(url, true)
                    end)
                    if ok and res then
                        body = res
                    end
                end

                return body
            end

            -- ============================================================================
            -- UTILITIES
            -- ============================================================================
            local function formatNumber(n)
                n = tonumber(n) or 0
                if n >= 1e12 then return string.format("%.2fT", n / 1e12)
                elseif n >= 1e9 then return string.format("%.2fB", n / 1e9)
                elseif n >= 1e6 then return string.format("%.2fM", n / 1e6)
                elseif n >= 1e3 then return string.format("%.2fK", n / 1e3) end
                return tostring(math.floor(n))
            end

            local function parseMoneyValue(value)
                if value == nil then return nil end
                if type(value) == "number" then return value end

                local s = tostring(value):gsub("[%s$,]", "")
                local numStr = s:match("[%d%.]+")
                if not numStr then return nil end

                local num = tonumber(numStr)
                if not num then return nil end

                local u = s:upper()
                if u:find("T") then return num * 1e12
                elseif u:find("B") then return num * 1e9
                elseif u:find("M") then return num * 1e6
                elseif u:find("K") then return num * 1e3 end
                return num
            end

            local function getField(tbl, keys)
                if type(tbl) ~= "table" then return nil end
                for _, k in ipairs(keys) do
                    local v = tbl[k]
                    if v ~= nil and v ~= "" then return v end
                end
                return nil
            end

            local function extractJobId(s)
                if type(s) ~= "string" then return nil end
                local id = s:match("[Gg]ameInstanceId=([%w%-]+)")
                        or s:match("[Jj]ob[Ii][Dd]=([%w%-]+)")
                if id and #id >= 32 then return id end
                return s:match("(%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x)")
            end

            -- ============================================================================
            -- FIREBASE DATA NORMALIZATION
            -- ============================================================================
            local function normalizeEntry(fbKey, rawData)
                if type(rawData) ~= "table" then return nil end

                local name = getField(rawData, {
                    "name","Name","nome","Nome","player","Player",
                    "username","Username","user","User","displayName","DisplayName",
                    "petName","PetName","display","Display","title","Title",
                    "nick","Nick","pet","Pet","Item","item"
                }) or "Unknown"

                local moneyRaw = getField(rawData, {
                    "money","Money","value","Value","gen","Gen",
                    "generations","Generations","amount","Amount",
                    "cash","Cash","total","Total","price","Price"
                })

                local jobId = getField(rawData, {
                    "jobId","JobId","jobID","JobID","serverId","serverID",
                    "job_id","id","Id","ID","server","Server",
                    "joinId","JoinId","job","Job","server_id"
                })

                local placeId = tonumber(getField(rawData, {
                    "placeId","PlaceId","placeID","PlaceID",
                    "place_id","gameId","GameId","game_id"
                })) or game.PlaceId

                if not jobId then
                    local linkBlob = rawData.join_game
                                  or rawData.join_script
                                  or rawData.link
                                  or rawData.url
                    jobId = extractJobId(linkBlob)
                end

                if type(jobId) ~= "string" or #jobId < 32 then
                    return nil
                end

                local numVal = parseMoneyValue(moneyRaw) or 0
                local uniqueId = tostring(fbKey) .. "_" .. tostring(jobId)

                return {
                    fbKey    = tostring(fbKey),
                    uniqueId = uniqueId,
                    nome     = tostring(name),
                    money    = (type(moneyRaw) == "string" and moneyRaw ~= "")
                               and moneyRaw or ("$" .. formatNumber(numVal)),
                    valor    = numVal,
                    jobId    = tostring(jobId),
                    placeId  = placeId,
                }
            end

            local function collectAll(snapshot)
                local out = {}
                if type(snapshot) ~= "table" then return out end

                for fbKey, rawData in pairs(snapshot) do
                    if type(rawData) == "table" then
                        local item = normalizeEntry(fbKey, rawData)
                        if item then
                            out[item.uniqueId] = item
                        else
                            for subKey, subData in pairs(rawData) do
                                if type(subData) == "table" then
                                    local subItem = normalizeEntry(subKey, subData)
                                    if subItem then
                                        out[subItem.uniqueId] = subItem
                                    end
                                end
                            end
                        end
                    end
                end
                return out
            end

            -- ============================================================================
            -- BLACKLIST HELPERS (exact-token match)
            -- ============================================================================
            local function isBlacklisted(name)
                if not name then return false end
                local lower = tostring(name):lower():match("^%s*(.-)%s*$")
                return State.BlackList[lower] ~= nil
            end

            local function addToBlacklist(name)
                local trimmed = name:match("^%s*(.-)%s*$")
                if trimmed == "" then return false, "Empty name" end
                local key = trimmed:lower()
                if State.BlackList[key] then return false, "Already in blacklist" end
                State.BlackList[key] = trimmed
                return true, trimmed
            end

            local function removeFromBlacklist(key)
                State.BlackList[key] = nil
            end

            -- ============================================================================
            -- UI CONSTRUCTION
            -- ============================================================================
            pcall(function()
                for _, c in pairs(CoreGui:GetChildren()) do
                    if c.Name == "AfgJoinerUI" then c:Destroy() end
                end
            end)

            local ScreenGui = Instance.new("ScreenGui")
            ScreenGui.Name = "AfgJoinerUI"
            ScreenGui.ResetOnSpawn = false
            local ok = pcall(function() ScreenGui.Parent = CoreGui end)
            if not ok then ScreenGui.Parent = Player:WaitForChild("PlayerGui") end

            local OPEN_POS = UDim2.new(0.5, -(GUI_WIDTH/2), 0.5, -(GUI_HEIGHT/2))

            local MainFrame = Instance.new("Frame")
            MainFrame.Name = "MainFrame"
            MainFrame.Parent = ScreenGui
            MainFrame.Size = UDim2.new(0, GUI_WIDTH, 0, GUI_HEIGHT)
            MainFrame.Position = OPEN_POS
            MainFrame.BackgroundColor3 = THEME.Background
            MainFrame.ClipsDescendants = true
            Instance.new("UICorner", MainFrame).CornerRadius = UDim.new(0, 12)

            local MainStroke = Instance.new("UIStroke", MainFrame)
            MainStroke.Color = THEME.Stroke
            MainStroke.Thickness = 1
            MainStroke.Transparency = 0.7

            -- ============================================================================
            -- HEADER
            -- ============================================================================
            local Header = Instance.new("Frame")
            Header.Name = "Header"
            Header.Parent = MainFrame
            Header.Size = UDim2.new(1, 0, 0, HEADER_HEIGHT)
            Header.BackgroundTransparency = 1

            local DragHandle = Instance.new("Frame")
            DragHandle.Name = "DragHandle"
            DragHandle.Parent = Header
            DragHandle.Size = UDim2.new(1, 0, 0, 34)
            DragHandle.BackgroundTransparency = 1
            DragHandle.Active = true

            local TitleLabel = Instance.new("TextLabel")
            TitleLabel.Parent = Header
            TitleLabel.Text = "Afg Joiner"
            TitleLabel.Font = Enum.Font.GothamBlack
            TitleLabel.TextSize = 14 * FONT_SIZE_MULTIPLIER
            TitleLabel.TextColor3 = THEME.TextWhite
            TitleLabel.Size = UDim2.new(1, -40, 0, 25)
            TitleLabel.Position = UDim2.new(0, 20, 0, 10)
            TitleLabel.BackgroundTransparency = 1
            TitleLabel.TextXAlignment = Enum.TextXAlignment.Left
            TitleLabel.TextTruncate = Enum.TextTruncate.AtEnd

            local TabBar = Instance.new("Frame")
            TabBar.Name = "TabBar"
            TabBar.Parent = Header
            TabBar.Size = UDim2.new(0, 200, 0, 26 * FONT_SIZE_MULTIPLIER)
            TabBar.Position = UDim2.new(0, 20, 0, 38)
            TabBar.BackgroundTransparency = 1

            local TabMonitor = Instance.new("TextButton")
            TabMonitor.Name = "TabMonitor"
            TabMonitor.Parent = TabBar
            TabMonitor.Text = "MONITOR"
            TabMonitor.Size = UDim2.new(0, 95, 1, 0)
            TabMonitor.BackgroundColor3 = THEME.Accent
            TabMonitor.TextColor3 = THEME.Background
            TabMonitor.Font = Enum.Font.GothamBold
            TabMonitor.TextSize = 10 * FONT_SIZE_MULTIPLIER
            Instance.new("UICorner", TabMonitor).CornerRadius = UDim.new(0, 6)

            local TabConfig = Instance.new("TextButton")
            TabConfig.Name = "TabConfig"
            TabConfig.Parent = TabBar
            TabConfig.Text = "CONFIG"
            TabConfig.Size = UDim2.new(0, 95, 1, 0)
            TabConfig.Position = UDim2.new(0, 100, 0, 0)
            TabConfig.BackgroundColor3 = THEME.ItemBG
            TabConfig.TextColor3 = THEME.TextGray
            TabConfig.Font = Enum.Font.GothamBold
            TabConfig.TextSize = 10 * FONT_SIZE_MULTIPLIER
            Instance.new("UICorner", TabConfig).CornerRadius = UDim.new(0, 6)

            local StatusLabel = Instance.new("TextLabel")
            StatusLabel.Name = "StatusLabel"
            StatusLabel.Parent = Header
            StatusLabel.Size = UDim2.new(1, -40, 0, 20)
            StatusLabel.Position = UDim2.new(0, 20, 0, HEADER_HEIGHT - 23)
            StatusLabel.BackgroundTransparency = 1
            StatusLabel.Text = "Connecting..."
            StatusLabel.TextColor3 = THEME.Accent
            StatusLabel.TextSize = 11 * FONT_SIZE_MULTIPLIER
            StatusLabel.Font = Enum.Font.Gotham
            StatusLabel.TextXAlignment = Enum.TextXAlignment.Left
            StatusLabel.TextTruncate = Enum.TextTruncate.AtEnd

            -- ============================================================================
            -- MONITOR PANEL
            -- ============================================================================
            local MonitorPanel = Instance.new("Frame")
            MonitorPanel.Name = "MonitorPanel"
            MonitorPanel.Parent = MainFrame
            MonitorPanel.Size = UDim2.new(1, 0, 1, -(HEADER_HEIGHT + 2))
            MonitorPanel.Position = UDim2.new(0, 0, 0, HEADER_HEIGHT)
            MonitorPanel.BackgroundTransparency = 1
            MonitorPanel.Visible = true

            local Controls = Instance.new("Frame")
            Controls.Name = "Controls"
            Controls.Parent = MonitorPanel
            Controls.Size = UDim2.new(1, -40, 0, CONTROLS_HEIGHT)
            Controls.Position = UDim2.new(0, 20, 0, 0)
            Controls.BackgroundTransparency = 1

            local AJButton = Instance.new("TextButton")
            AJButton.Name = "AJButton"
            AJButton.Parent = Controls
            AJButton.Text = "AUTO JOIN: OFF"
            AJButton.Size = UDim2.new(0, 130 * SCALE, 1, 0)
            AJButton.BackgroundColor3 = THEME.ItemBG
            AJButton.TextColor3 = THEME.TextWhite
            AJButton.Font = Enum.Font.GothamBold
            AJButton.TextSize = 10 * FONT_SIZE_MULTIPLIER
            Instance.new("UICorner", AJButton).CornerRadius = UDim.new(0, 8)

            local ValueInput = Instance.new("TextBox")
            ValueInput.Name = "ValueInput"
            ValueInput.Parent = Controls
            ValueInput.Text = "10M"
            ValueInput.Size = UDim2.new(1, -(130 * SCALE + 10), 1, 0)
            ValueInput.Position = UDim2.new(0, 130 * SCALE + 10, 0, 0)
            ValueInput.BackgroundColor3 = THEME.ItemBG
            ValueInput.TextColor3 = THEME.TextWhite
            ValueInput.Font = Enum.Font.GothamBold
            ValueInput.TextSize = 11 * FONT_SIZE_MULTIPLIER
            ValueInput.ClearTextOnFocus = false
            Instance.new("UICorner", ValueInput).CornerRadius = UDim.new(0, 8)

            local Scroll = Instance.new("ScrollingFrame")
            Scroll.Name = "Scroll"
            Scroll.Parent = MonitorPanel
            Scroll.Size = UDim2.new(1, -40, 1, -(CONTROLS_HEIGHT + 10))
            Scroll.Position = UDim2.new(0, 20, 0, CONTROLS_HEIGHT + 10)
            Scroll.BackgroundTransparency = 1
            Scroll.ScrollBarThickness = 3
            Scroll.ScrollBarImageColor3 = THEME.Accent
            Scroll.ClipsDescendants = true

            local ListLayout = Instance.new("UIListLayout")
            ListLayout.Parent = Scroll
            ListLayout.Padding = UDim.new(0, 4)
            ListLayout.SortOrder = Enum.SortOrder.LayoutOrder
            ListLayout:GetPropertyChangedSignal("AbsoluteContentSize"):Connect(function()
                Scroll.CanvasSize = UDim2.new(0, 0, 0, ListLayout.AbsoluteContentSize.Y + 10)
            end)

            -- ============================================================================
            -- CONFIG PANEL
            -- ============================================================================
            local ConfigPanel = Instance.new("Frame")
            ConfigPanel.Name = "ConfigPanel"
            ConfigPanel.Parent = MainFrame
            ConfigPanel.Size = UDim2.new(1, 0, 1, -(HEADER_HEIGHT + 2))
            ConfigPanel.Position = UDim2.new(0, 0, 0, HEADER_HEIGHT)
            ConfigPanel.BackgroundTransparency = 1
            ConfigPanel.Visible = false

            local MinSection = Instance.new("Frame")
            MinSection.Name = "MinSection"
            MinSection.Parent = ConfigPanel
            MinSection.Size = UDim2.new(1, -40, 0, 62 * SCALE)
            MinSection.Position = UDim2.new(0, 20, 0, 4)
            MinSection.BackgroundColor3 = THEME.ItemBG
            Instance.new("UICorner", MinSection).CornerRadius = UDim.new(0, 8)

            local MinTitle = Instance.new("TextLabel")
            MinTitle.Parent = MinSection
            MinTitle.Text = "⚙ Minimum (10M+)"
            MinTitle.Size = UDim2.new(1, -12, 0, 22 * FONT_SIZE_MULTIPLIER)
            MinTitle.Position = UDim2.new(0, 12, 0, 6)
            MinTitle.Font = Enum.Font.GothamBold
            MinTitle.TextSize = 11 * FONT_SIZE_MULTIPLIER
            MinTitle.TextColor3 = THEME.TextWhite
            MinTitle.BackgroundTransparency = 1
            MinTitle.TextXAlignment = Enum.TextXAlignment.Left

            local MinInputConfig = Instance.new("TextBox")
            MinInputConfig.Name = "MinInputConfig"
            MinInputConfig.Parent = MinSection
            MinInputConfig.Text = "10M"
            MinInputConfig.Size = UDim2.new(0, 100 * SCALE, 0, 22 * FONT_SIZE_MULTIPLIER)
            MinInputConfig.Position = UDim2.new(1, -(100 * SCALE + 12), 0, 20)
            MinInputConfig.BackgroundColor3 = THEME.Background
            MinInputConfig.TextColor3 = THEME.Accent
            MinInputConfig.Font = Enum.Font.GothamBold
            MinInputConfig.TextSize = 11 * FONT_SIZE_MULTIPLIER
            MinInputConfig.ClearTextOnFocus = false
            Instance.new("UICorner", MinInputConfig).CornerRadius = UDim.new(0, 6)

            local BLSection = Instance.new("Frame")
            BLSection.Name = "BLSection"
            BLSection.Parent = ConfigPanel
            BLSection.Size = UDim2.new(1, -40, 1, -(62 * SCALE + 12))
            BLSection.Position = UDim2.new(0, 20, 0, 62 * SCALE + 8)
            BLSection.BackgroundColor3 = THEME.ItemBG
            Instance.new("UICorner", BLSection).CornerRadius = UDim.new(0, 8)

            local BLTitle = Instance.new("TextLabel")
            BLTitle.Parent = BLSection
            BLTitle.Text = "🚫 Blacklist"
            BLTitle.Size = UDim2.new(1, -12, 0, 22 * FONT_SIZE_MULTIPLIER)
            BLTitle.Position = UDim2.new(0, 12, 0, 6)
            BLTitle.Font = Enum.Font.GothamBold
            BLTitle.TextSize = 11 * FONT_SIZE_MULTIPLIER
            BLTitle.TextColor3 = THEME.TextWhite
            BLTitle.BackgroundTransparency = 1
            BLTitle.TextXAlignment = Enum.TextXAlignment.Left

            local BLInputRow = Instance.new("Frame")
            BLInputRow.Name = "BLInputRow"
            BLInputRow.Parent = BLSection
            BLInputRow.Size = UDim2.new(1, -20, 0, 30 * SCALE)
            BLInputRow.Position = UDim2.new(0, 10, 0, 30 * SCALE)
            BLInputRow.BackgroundTransparency = 1

            local BLInput = Instance.new("TextBox")
            BLInput.Name = "BLInput"
            BLInput.Parent = BLInputRow
            BLInput.PlaceholderText = "Pet name"
            BLInput.Text = ""
            BLInput.Size = UDim2.new(1, -(34 * SCALE + 8), 1, 0)
            BLInput.BackgroundColor3 = THEME.Background
            BLInput.TextColor3 = THEME.TextWhite
            BLInput.PlaceholderColor3 = THEME.TextGray
            BLInput.Font = Enum.Font.Gotham
            BLInput.TextSize = 10 * FONT_SIZE_MULTIPLIER
            BLInput.ClearTextOnFocus = false
            Instance.new("UICorner", BLInput).CornerRadius = UDim.new(0, 6)

            local BLAddBtn = Instance.new("TextButton")
            BLAddBtn.Name = "BLAddBtn"
            BLAddBtn.Parent = BLInputRow
            BLAddBtn.Text = "+"
            BLAddBtn.Size = UDim2.new(0, 34 * SCALE, 1, 0)
            BLAddBtn.Position = UDim2.new(1, -(34 * SCALE), 0, 0)
            BLAddBtn.BackgroundColor3 = THEME.Accent
            BLAddBtn.TextColor3 = THEME.Background
            BLAddBtn.Font = Enum.Font.GothamBlack
            BLAddBtn.TextSize = 18 * FONT_SIZE_MULTIPLIER
            Instance.new("UICorner", BLAddBtn).CornerRadius = UDim.new(0, 6)

            local BLFeedback = Instance.new("TextLabel")
            BLFeedback.Name = "BLFeedback"
            BLFeedback.Parent = BLSection
            BLFeedback.Text = ""
            BLFeedback.Size = UDim2.new(1, -20, 0, 14 * FONT_SIZE_MULTIPLIER)
            BLFeedback.Position = UDim2.new(0, 10, 0, 64 * SCALE)
            BLFeedback.Font = Enum.Font.Gotham
            BLFeedback.TextSize = 9 * FONT_SIZE_MULTIPLIER
            BLFeedback.TextColor3 = THEME.GreenActive
            BLFeedback.BackgroundTransparency = 1
            BLFeedback.TextXAlignment = Enum.TextXAlignment.Left

            local BLScroll = Instance.new("ScrollingFrame")
            BLScroll.Name = "BLScroll"
            BLScroll.Parent = BLSection
            BLScroll.Size = UDim2.new(1, -20, 1, -(80 * SCALE + 20))
            BLScroll.Position = UDim2.new(0, 10, 0, 80 * SCALE + 16)
            BLScroll.BackgroundTransparency = 1
            BLScroll.ScrollBarThickness = 3
            BLScroll.ScrollBarImageColor3 = THEME.Accent
            BLScroll.ClipsDescendants = true

            local BLListLayout = Instance.new("UIListLayout")
            BLListLayout.Parent = BLScroll
            BLListLayout.Padding = UDim.new(0, 4)
            BLListLayout.SortOrder = Enum.SortOrder.LayoutOrder
            BLListLayout:GetPropertyChangedSignal("AbsoluteContentSize"):Connect(function()
                BLScroll.CanvasSize = UDim2.new(0, 0, 0, BLListLayout.AbsoluteContentSize.Y + 6)
            end)

            -- ============================================================================
            -- BLACKLIST UI FUNCTIONS
            -- ============================================================================
            local function refreshBLFeedback(msg, color)
                BLFeedback.Text = msg
                BLFeedback.TextColor3 = color or THEME.GreenActive
                task.delay(2, function()
                    pcall(function()
                        if BLFeedback.Text == msg then
                            BLFeedback.Text = ""
                        end
                    end)
                end)
            end

            local rowOrder = 0
            local function nextOrder()
                rowOrder = rowOrder + 1
                return rowOrder
            end

            local function createBLRow(displayName, key)
                local Row = Instance.new("Frame")
                Row.Name = "BL_" .. key
                Row.Parent = BLScroll
                Row.LayoutOrder = nextOrder()
                Row.Size = UDim2.new(1, 0, 0, 28 * SCALE)
                Row.BackgroundColor3 = THEME.Background
                Instance.new("UICorner", Row).CornerRadius = UDim.new(0, 6)

                local NameL = Instance.new("TextLabel")
                NameL.Parent = Row
                NameL.Text = "🚫 " .. displayName
                NameL.Size = UDim2.new(1, -(32 * SCALE + 4), 1, 0)
                NameL.Position = UDim2.new(0, 8, 0, 0)
                NameL.Font = Enum.Font.Gotham
                NameL.TextSize = 10 * FONT_SIZE_MULTIPLIER
                NameL.TextColor3 = THEME.TextWhite
                NameL.BackgroundTransparency = 1
                NameL.TextXAlignment = Enum.TextXAlignment.Left
                NameL.TextTruncate = Enum.TextTruncate.AtEnd

                local DelBtn = Instance.new("TextButton")
                DelBtn.Parent = Row
                DelBtn.Text = "✕"
                DelBtn.Size = UDim2.new(0, 28 * SCALE, 0, 20 * SCALE)
                DelBtn.Position = UDim2.new(1, -(28 * SCALE + 4), 0.5, -(10 * SCALE))
                DelBtn.BackgroundColor3 = THEME.RedSoft
                DelBtn.TextColor3 = THEME.TextWhite
                DelBtn.Font = Enum.Font.GothamBold
                DelBtn.TextSize = 10 * FONT_SIZE_MULTIPLIER
                Instance.new("UICorner", DelBtn).CornerRadius = UDim.new(0, 4)
                DelBtn.MouseButton1Click:Connect(function()
                    removeFromBlacklist(key)
                    Row:Destroy()
                    refreshBLFeedback("Removed: " .. displayName, THEME.RedSoft)
                end)
            end

            local function tryAddFromBLInput()
                local text = BLInput.Text
                local added, result = addToBlacklist(text)
                if added then
                    createBLRow(result, result:lower())
                    BLInput.Text = ""
                    refreshBLFeedback("Added: " .. result, THEME.GreenActive)
                else
                    refreshBLFeedback("⚠ " .. result, THEME.RedSoft)
                end
            end

            BLAddBtn.MouseButton1Click:Connect(tryAddFromBLInput)
            BLInput.FocusLost:Connect(function(enterPressed)
                if enterPressed then tryAddFromBLInput() end
            end)

            -- ============================================================================
            -- DISCORD BUTTON
            -- ============================================================================
            local DiscordButton = Instance.new("Frame")
            DiscordButton.Name = "DiscordButton"
            DiscordButton.Parent = ScreenGui
            DiscordButton.Size = UDim2.new(0, GUI_WIDTH, 0, DISCORD_HEIGHT)
            DiscordButton.Position = UDim2.new(OPEN_POS.X.Scale, OPEN_POS.X.Offset,
                                                OPEN_POS.Y.Scale, OPEN_POS.Y.Offset + GUI_HEIGHT)
            DiscordButton.BackgroundColor3 = THEME.SidebarBG
            Instance.new("UICorner", DiscordButton).CornerRadius = UDim.new(0, 8)

            local DiscordLabel = Instance.new("TextLabel")
            DiscordLabel.Parent = DiscordButton
            DiscordLabel.Size = UDim2.new(1, 0, 1, 0)
            DiscordLabel.BackgroundTransparency = 1
            DiscordLabel.Text = "Discord: discord.gg/zeUKa7ksD9"
            DiscordLabel.TextColor3 = THEME.DiscordAccent
            DiscordLabel.TextSize = 11 * FONT_SIZE_MULTIPLIER
            DiscordLabel.Font = Enum.Font.GothamBold

            local DiscordClick = Instance.new("TextButton")
            DiscordClick.Parent = DiscordButton
            DiscordClick.Size = UDim2.new(1, 0, 1, 0)
            DiscordClick.BackgroundTransparency = 1
            DiscordClick.Text = ""
            DiscordClick.MouseButton1Click:Connect(function()
                pcall(function() setclipboard("discord.gg/zeUKa7ksD9") end)
            end)

            -- ============================================================================
            -- TOGGLE BUTTON
            -- ============================================================================
            local ToggleFrame = Instance.new("Frame")
            ToggleFrame.Name = "ToggleFrame"
            ToggleFrame.Parent = ScreenGui
            ToggleFrame.Size = UDim2.new(0, TOGGLE_SIZE, 0, TOGGLE_SIZE)
            ToggleFrame.Position = UDim2.new(0, 10, 0.5, -(TOGGLE_SIZE/2))
            ToggleFrame.BackgroundColor3 = THEME.Background
            Instance.new("UICorner", ToggleFrame).CornerRadius = UDim.new(0, 10)

            local ToggleBtn = Instance.new("TextButton")
            ToggleBtn.Parent = ToggleFrame
            ToggleBtn.Text = "AFG"
            ToggleBtn.Size = UDim2.new(1, 0, 1, 0)
            ToggleBtn.BackgroundTransparency = 1
            ToggleBtn.TextColor3 = THEME.Accent
            ToggleBtn.Font = Enum.Font.GothamBlack
            ToggleBtn.TextSize = 14 * FONT_SIZE_MULTIPLIER
            ToggleBtn.ZIndex = 1
            ToggleBtn.MouseButton1Click:Connect(function()
                local vis = not MainFrame.Visible
                MainFrame.Visible = vis
                DiscordButton.Visible = vis
            end)

            -- ============================================================================
            -- TAB LOGIC
            -- ============================================================================
            local function switchTab(tab)
                State.ActiveTab = tab
                if tab == "MONITOR" then
                    MonitorPanel.Visible = true
                    ConfigPanel.Visible  = false
                    TabMonitor.BackgroundColor3 = THEME.Accent
                    TabMonitor.TextColor3       = THEME.Background
                    TabConfig.BackgroundColor3  = THEME.ItemBG
                    TabConfig.TextColor3        = THEME.TextGray
                else
                    MonitorPanel.Visible = false
                    ConfigPanel.Visible  = true
                    TabConfig.BackgroundColor3  = THEME.Accent
                    TabConfig.TextColor3        = THEME.Background
                    TabMonitor.BackgroundColor3 = THEME.ItemBG
                    TabMonitor.TextColor3       = THEME.TextGray
                end
            end

            TabMonitor.MouseButton1Click:Connect(function() switchTab("MONITOR") end)
            TabConfig.MouseButton1Click:Connect(function() switchTab("CONFIG") end)

            -- ============================================================================
            -- STATUS
            -- ============================================================================
            local function setStatus(txt, color)
                pcall(function()
                    StatusLabel.Text = txt
                    StatusLabel.TextColor3 = color or THEME.TextGray
                end)
            end

            -- ============================================================================
            -- MIN FILTER SYNC
            -- ============================================================================
            local function applyMinFilterFrom(textBox, mirrorBox)
                local v = parseMoneyValue(textBox.Text)
                if v and v >= 0 then
                    State.MinGenFilter = v
                    local formatted = (v == 0) and "0" or formatNumber(v)
                    textBox.Text = formatted
                    if mirrorBox then mirrorBox.Text = formatted end
                    setStatus("Filter: " .. formatted, THEME.Accent)
                else
                    textBox.Text = formatNumber(State.MinGenFilter)
                    setStatus("Invalid filter input", THEME.RedSoft)
                end
            end

            MinInputConfig.FocusLost:Connect(function()
                applyMinFilterFrom(MinInputConfig, ValueInput)
            end)

            ValueInput.FocusLost:Connect(function()
                applyMinFilterFrom(ValueInput, MinInputConfig)
            end)

            State.MinGenFilter = parseMoneyValue(ValueInput.Text) or MIN_VAL

            -- ============================================================================
            -- AUTO-JOIN BUTTON
            -- ============================================================================
            AJButton.MouseButton1Click:Connect(function()
                State.AutoJoin = not State.AutoJoin
                AJButton.Text = "AUTO JOIN: " .. (State.AutoJoin and "ON" or "OFF")
                AJButton.BackgroundColor3 = State.AutoJoin and THEME.Accent or THEME.ItemBG
                AJButton.TextColor3 = State.AutoJoin and THEME.Background or THEME.TextWhite
            end)

            --============================================================================
            -- MONITOR ROW FACTORY (continued)
            -- ============================================================================
            local function capRows()
                local frames = {}
                for _, c in ipairs(Scroll:GetChildren()) do
                    if c:IsA("Frame") then
                        frames[#frames + 1] = c
                    end
                end
                -- UIListLayout sorts by LayoutOrder, so first inserted = oldest
                table.sort(frames, function(a, b)
                    return a.LayoutOrder < b.LayoutOrder
                end)
                while #frames > MAX_ROWS do
                    frames[1]:Destroy()
                    table.remove(frames, 1)
                end
            end

            local function createRow(data)
                local Row = Instance.new("Frame")
                Row.Name = "Row_" .. data.uniqueId
                Row.Parent = Scroll
                Row.LayoutOrder = nextOrder()
                Row.Size = UDim2.new(1, 0, 0, ROW_HEIGHT)
                Row.BackgroundColor3 = THEME.ItemBG
                Instance.new("UICorner", Row).CornerRadius = UDim.new(0, 8)
                local rs = Instance.new("UIStroke", Row)
                rs.Color = THEME.Stroke
                rs.Thickness = 1

                local NameL = Instance.new("TextLabel")
                NameL.Parent = Row
                NameL.Text = data.nome
                NameL.Size = UDim2.new(0.5, -20, 1, 0)
                NameL.Position = UDim2.new(0, 12, 0, 0)
                NameL.Font = Enum.Font.GothamBold
                NameL.TextSize = 12 * FONT_SIZE_MULTIPLIER
                NameL.TextColor3 = THEME.TextWhite
                NameL.BackgroundTransparency = 1
                NameL.TextXAlignment = Enum.TextXAlignment.Left
                NameL.TextYAlignment = Enum.TextYAlignment.Center
                NameL.TextTruncate = Enum.TextTruncate.AtEnd

                local ValueL = Instance.new("TextLabel")
                ValueL.Parent = Row
                ValueL.Text = data.money
                ValueL.Size = UDim2.new(0.3, -10, 1, 0)
                ValueL.Position = UDim2.new(0.5, 0, 0, 0)
                ValueL.Font = Enum.Font.GothamBold
                ValueL.TextColor3 = THEME.Accent
                ValueL.TextSize = 13 * FONT_SIZE_MULTIPLIER
                ValueL.BackgroundTransparency = 1
                ValueL.TextXAlignment = Enum.TextXAlignment.Center
                ValueL.TextYAlignment = Enum.TextYAlignment.Center
                ValueL.TextTruncate = Enum.TextTruncate.AtEnd

                local Join = Instance.new("TextButton")
                Join.Parent = Row
                Join.Text = "JOIN"
                Join.Size = UDim2.new(0, 65 * SCALE, 0, 32 * SCALE)
                Join.Position = UDim2.new(1, -(65 * SCALE + 10), 0.5, -(16 * SCALE))
                Join.BackgroundColor3 = THEME.Accent
                Join.TextColor3 = THEME.TextWhite
                Join.Font = Enum.Font.GothamBold
                Join.TextSize = 11 * FONT_SIZE_MULTIPLIER
                Instance.new("UICorner", Join).CornerRadius = UDim.new(0, 6)

                Join.MouseButton1Click:Connect(function()
                    local now = tick()
                    if now < joinLockUntil then return end   -- debounce
                    joinLockUntil = now + JOIN_COOLDOWN

                    setStatus("Joining: " .. data.nome, THEME.Accent)
                    pcall(function()
                        TeleportService:TeleportToPlaceInstance(
                            data.placeId or game.PlaceId,
                            data.jobId,
                            Player
                        )
                    end)
                end)

                capRows()
            end

            -- ============================================================================
            -- FETCH FROM FIREBASE
            -- ============================================================================
            local function fetchFromFirebase()
                local cacheBuster = tostring(math.random(100000, 999999)) .. "_" .. tostring(tick())
                local url = FIREBASE_URL .. "?t=" .. cacheBuster
                local body = httpRequest(url)

                if not body or body == "" or body:lower() == "null" then
                    return nil
                end

                local ok, decoded = pcall(HttpService.JSONDecode, HttpService, body)
                if ok and type(decoded) == "table" then
                    return decoded
                end
                return nil
            end

            -- ============================================================================
            -- AUTO-JOIN QUEUE (non-blocking)
            -- ============================================================================
            local function processQueue()
                if isProcessing then return end
                isProcessing = true

                task.spawn(function()
                    while #joinQueue > 0 and State.AutoJoin do
                        local item = table.remove(joinQueue, 1)
                        if item and item.jobId then
                            setStatus("⚡ Joining: " .. item.nome, THEME.Accent)

                            local ok = pcall(function()
                                TeleportService:TeleportToPlaceInstance(
                                    item.placeId or game.PlaceId,
                                    item.jobId,
                                    Player
                                )
                            end)

                            -- If teleport failed, drop and continue quickly.
                            -- If it succeeded the client usually leaves the game anyway.
                            task.wait(ok and AJ_DELAY or 1)
                        end
                    end
                    isProcessing = false
                end)
            end

            local function addToQueue(item)
                if not item or not item.jobId then return end
                table.insert(joinQueue, item)
                if State.AutoJoin then
                    processQueue()
                end
            end

            -- ============================================================================
            -- PROCESSED-ID PRUNING
            -- ============================================================================
            task.spawn(function()
                while true do
                    task.wait(60)
                    local now = tick()
                    for id, ts in pairs(processedIds) do
                        if now - ts > PROCESSED_TTL then
                            processedIds[id] = nil
                        end
                    end
                end
            end)

            -- ============================================================================
            -- MAIN POLLING LOOP
            -- ============================================================================
            task.spawn(function()
                local failCount = 0
                local connected = false
                local IsFirstFetch = true

                while true do
                    task.wait(POLL_INTERVAL)

                    local currentData = fetchFromFirebase()

                    if currentData then
                        if not connected then
                            connected = true
                            setStatus("Connected", THEME.GreenActive)
                        end

                        failCount = 0
                        local current = collectAll(currentData)
                        local newItems = {}

                        for uniqueId, item in pairs(current) do
                            if not processedIds[uniqueId] then
                                processedIds[uniqueId] = tick()

                                if not IsFirstFetch then
                                    if not isBlacklisted(item.nome)
                                       and item.valor >= State.MinGenFilter then
                                        table.insert(newItems, item)
                                    end
                                end
                            end
                        end

                        for _, item in ipairs(newItems) do
                            pcall(function()
                                createRow(item)
                            end)
                            task.defer(function()
                                pcall(function()
                                    Scroll.CanvasPosition =
                                        Vector2.new(0, Scroll.CanvasSize.Y.Offset)
                                end)
                            end)

                            setStatus("🚀 " .. item.nome .. " (" .. item.money .. ")",
                                      THEME.GreenActive)

                            if State.AutoJoin then
                                addToQueue(item)
                            end
                        end

                        IsFirstFetch = false

                        if not StatusLabel.Text:find("🚀")
                           and not StatusLabel.Text:find("⚡") then
                            setStatus("Monitoring... " .. os.date("%H:%M:%S"),
                                      THEME.TextGray)
                        end
                    else
                        failCount = failCount + 1
                        connected = false
                        setStatus("Reconnecting (" .. failCount .. ")", THEME.RedSoft)
                        if failCount >= 5 then
                            task.wait(2)
                        end
                    end
                end
            end)

            -- ============================================================================
            -- DRAGGABLE (leak-free)
            -- ============================================================================
            local function makeDraggable(obj, handle, others)
                local dragging, inputStart, startPos = false, nil, nil

                handle.InputBegan:Connect(function(input)
                    if input.UserInputType == Enum.UserInputType.MouseButton1
                    or input.UserInputType == Enum.UserInputType.Touch then
                        dragging = true
                        inputStart = input.Position
                        startPos = obj.Position
                    end
                end)

                UserInputService.InputChanged:Connect(function(input)
                    if input.UserInputState == Enum.UserInputState.End then
                        dragging = false
                        return
                    end
                    if not dragging then return end
                    if input.UserInputType ~= Enum.UserInputType.MouseMovement
                    and input.UserInputType ~= Enum.UserInputType.Touch then return end

                    local delta = input.Position - inputStart
                    local newPos = UDim2.new(
                        startPos.X.Scale, startPos.X.Offset + delta.X,
                        startPos.Y.Scale, startPos.Y.Offset + delta.Y
                    )
                    obj.Position = newPos
                    if others then
                        for _, o in ipairs(others) do
                            o.obj.Position = UDim2.new(
                                newPos.X.Scale, newPos.X.Offset + o.offX,
                                newPos.Y.Scale, newPos.Y.Offset + o.offY
                            )
                        end
                    end
                end)
            end

            makeDraggable(MainFrame, DragHandle, {
                {obj = DiscordButton, offX = 0, offY = GUI_HEIGHT},
            })
            makeDraggable(ToggleFrame, ToggleBtn)

            print("[Afg Joiner] Loaded! (NO LAG - OPTIMIZED)")
            print("[Afg Joiner] Mode: " .. (isMobile and "MOBILE" or "PC"))
            print("[Afg Joiner] Polling: " .. POLL_INTERVAL .. "s | Min: " .. formatNumber(MIN_VAL))
            print("[Afg Joiner] Auto-Join Delay: " .. AJ_DELAY .. "s")
        end)

        if success then
            break
        end

        warn("[Afg Joiner] Load failed (attempt " .. attempt .. "):", err)
        if attempt >= 5 then
            warn("[Afg Joiner] Giving up after 5 attempts.")
            break
        end
        task.wait(2)
    end
end

safeLoad()

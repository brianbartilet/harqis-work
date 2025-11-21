-- Fast, looping typewriter + scroll-up (teleprompter style)

local text = ""
local index = 0

local filePath
local speedMin
local speedMax
local maxLines

local function loadFile()
    local f = io.open(filePath, "r")
    if not f then
        text = "(file not found: " .. tostring(filePath or "(nil)") .. ")"
    else
        text = f:read("*a") or ""
        f:close()
        if text == "" then
            text = "(empty file)"
        end
    end

    index = 0
end

function Initialize()
    filePath  = SELF:GetOption("FileToRead", SKIN:GetVariable("TextFile", "dump.txt"))

    -- very fast typing (per update)
    speedMin  = tonumber(SELF:GetOption("SpeedMin",  SKIN:GetVariable("SpeedMin", "30"))) or 30
    speedMax  = tonumber(SELF:GetOption("SpeedMax",  SKIN:GetVariable("SpeedMax", "80"))) or 80

    -- number of visible lines (scroll window)
    maxLines  = tonumber(SELF:GetOption("MaxLines", SKIN:GetVariable("MaxLines", "16"))) or 16

    math.randomseed(os.time())
    loadFile()
end

local function advance()
    -- random burst between speedMin and speedMax chars/update
    local step = math.random(speedMin, speedMax)
    index = index + step

    -- continuous loop: when we reach end, start again
    if index > #text then
        index = 0
    end
end

function Update()
    if text == "" then return "" end

    advance()

    local endIndex = math.min(index, #text)
    if endIndex <= 0 then
        return ""
    end

    local visible = string.sub(text, 1, endIndex)

    -- Scroll effect: keep only last maxLines lines
    local lines = {}
    for line in visible:gmatch("([^\n]*)\n?") do
        table.insert(lines, line)
    end

    local total = #lines
    if total > maxLines then
        local startLine = total - maxLines + 1
        return table.concat(lines, "\n", startLine, total)
    else
        return visible
    end
end

function Reset()
    index = 0
    return 0
end

function ReloadFile()
    loadFile()
    return 0
end

-- TextCycle.lua  – scroll dump.txt like a teleprompter

local lines       = {}
local offset      = 1
local frame       = 0

local filePath
local maxLines
local scrollDelay
local wrapAt

local function appendWrappedLine(target, line)
    if line:match("^%s*$") then
        target[#target + 1] = ""
        return
    end

    if not wrapAt or wrapAt <= 0 or #line <= wrapAt then
        target[#target + 1] = line
        return
    end

    local remaining = line
    local continuationIndent = line:match("^(%s*)") or ""
    if #continuationIndent >= wrapAt then
        continuationIndent = ""
    end

    while #remaining > wrapAt do
        local breakAt = wrapAt
        local nextAt = wrapAt + 1

        -- Prefer a word boundary, but hard-wrap unusually long tokens so one
        -- source line can never expand into an unbounded number of meter rows.
        for i = wrapAt, 1, -1 do
            local char = remaining:sub(i, i)
            if char == " " or char == "\t" then
                breakAt = i - 1
                nextAt = i + 1
                break
            end
        end

        local part = remaining:sub(1, breakAt):gsub("%s+$", "")
        target[#target + 1] = part
        remaining = remaining:sub(nextAt):gsub("^%s+", "")
        if continuationIndent ~= "" then
            remaining = continuationIndent .. remaining
        end
    end

    target[#target + 1] = remaining
end

-- Called once when the measure initializes
function Initialize()
    -- Read options / variables
    filePath = SELF:GetOption("FileToRead", SKIN:GetVariable("TextFile", "dump.txt"))
    maxLines = tonumber(SKIN:GetVariable("MaxLines", "16")) or 16
    scrollDelay = tonumber(SKIN:GetVariable("ScrollDelay", "2")) or 2
    wrapAt = tonumber(SKIN:GetVariable("WrapAt", "0")) or 0

    readFile()
end

local function safeFilePath()
    return tostring(filePath or "(nil)")
end

function readFile()
    lines = {}

    local f = io.open(filePath, "r")
    if not f then
        lines = { "(file not found: " .. safeFilePath() .. ")" }
    else
        for l in f:lines() do
            appendWrappedLine(lines, l)
        end
        f:close()

        if #lines == 0 then
            lines = { "(empty file)" }
        end
    end

    offset = 1
    frame  = 0
end

-- Called every update
function Update()
    if #lines == 0 then
        return ""
    end

    -- Scroll timing: every `scrollDelay` updates, move down by 1 line
    frame = frame + 1
    if frame >= scrollDelay then
        frame = 0
        offset = offset + 1
        if offset > #lines then
            offset = 1
        end
    end

    -- Build visible window of text
    local buf = {}
    for i = 0, maxLines - 1 do
        local idx = offset + i
        if idx > #lines then
            idx = idx - #lines
        end
        buf[#buf + 1] = lines[idx]
    end

    -- IMPORTANT: return the *string* directly
    return table.concat(buf, "\n")
end

-- Optional: can be called from bangs
function ReloadFile()
    readFile()
    return 0
end

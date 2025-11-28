local textFile
local linesPerPage
local scrollIndex = 0
local lines = {}
local maxIndex = 0

function Initialize()
    textFile = SKIN:GetVariable('TextFile')
    linesPerPage = tonumber(SKIN:GetVariable('LinesPerPage')) or 20
    scrollIndex = 0
    LoadFile()
end

function LoadFile()
    lines = {}
    local filePath = SKIN:MakePathAbsolute(textFile)
    local f = io.open(filePath, "r")
    if not f then
        lines = { "Error: could not open file:", filePath }
        maxIndex = 0
        scrollIndex = 0
        return
    end

    for line in f:lines() do
        table.insert(lines, line)
    end
    f:close()

    if #lines == 0 then
        lines = { "(File is empty)" }
    end

    maxIndex = math.max(0, #lines - linesPerPage)
    if scrollIndex > maxIndex then
        scrollIndex = maxIndex
    end
end

function ReloadFile()
    LoadFile()
    -- force refresh
    SKIN:Bang('!UpdateMeasure', SELF:GetName())
    SKIN:Bang('!UpdateMeter', 'MeterText')
    SKIN:Bang('!Redraw')
end

function Update()
    local startLine = scrollIndex + 1
    local endLine = math.min(#lines, startLine + linesPerPage - 1)

    local buffer = {}
    for i = startLine, endLine do
        table.insert(buffer, lines[i])
    end

    return table.concat(buffer, "\n")
end

function Scroll(delta)
    delta = tonumber(delta) or 0
    if delta == 0 then return end

    local newIndex = scrollIndex + delta

    if newIndex < 0 then
        newIndex = 0
    elseif newIndex > maxIndex then
        newIndex = maxIndex
    end

    if newIndex ~= scrollIndex then
        scrollIndex = newIndex
        SKIN:Bang('!UpdateMeasure', SELF:GetName())

        SKIN:Bang('!Redraw')
    end
end

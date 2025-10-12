[Metadata]
; Contains basic information of the skin.
Name=World Clocks for illustra
Author=poiru | eclectic-tech
Information=Displays the current day and time for 5 locations.
License=Creative Commons BY-NC-SA 3.0
Version=1.2020.08.12

; Location1
[MeasureName1]
Measure=Plugin
Plugin=Plugins\WebParser.dll
UpdateRate=600
Url="http://time.yandex.com/sync.json?lang=en&geo=#Location1#"
Debug=1
RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
StringIndex=1
DecodeCharacterReference=1
DynamicVariables=1
Substitute="":"Updating.Yandex"
Disabled=1
FinishAction=[!EnableMeasure MeasureName2][!UpdateMeasure MeasureName2]
; Each location WebParser measure is disabled on load. Then each is enabled, when the previous one is finished. 
; This prevents multiple WebParser measure from running simultaneously, which could lock up the WebParser.dll
 
[MeasureOffset1]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName1]
StringIndex=2
Substitute="":"0"

[MeasureOffsetString1]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName1]
StringIndex=3
Substitute="UTC":"GMT"

[MeasureTime1]
Measure=Time
Format=%a %#I:%M
TimeZone=([MeasureOffset1]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

[MeasureAMPM1]
Measure=Time
Format=%p
TimeZone=([MeasureOffset1]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

; Location2
[MeasureName2]
Measure=Plugin
Plugin=Plugins\WebParser.dll
UpdateRate=600
Url="http://time.yandex.com/sync.json?lang=en&geo=#Location2#"
Debug=1
RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
StringIndex=1
DecodeCharacterReference=1
DynamicVariables=1
Substitute="":"Updating.Yandex"
Disabled=1
FinishAction=[!EnableMeasure MeasureName3][!UpdateMeasure MeasureName3]

[MeasureOffset2]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName2]
StringIndex=2
Substitute="":"0"

[MeasureOffsetString2]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName2]
StringIndex=3
Substitute="UTC":"GMT"

[MeasureTime2]
Measure=Time
Format=%a %#I:%M
TimeZone=([MeasureOffset2]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

[MeasureAMPM2]
Measure=Time
Format=%p
TimeZone=([MeasureOffset2]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

; Location3
[MeasureName3]
Measure=Plugin
Plugin=Plugins\WebParser.dll
UpdateRate=600
Url="http://time.yandex.com/sync.json?lang=en&geo=#Location3#"
Debug=1
RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
StringIndex=1
DecodeCharacterReference=1
DynamicVariables=1
Substitute="":"Updating.Yandex"
Disabled=1
FinishAction=[!EnableMeasure MeasureName4][!UpdateMeasure MeasureName4]

[MeasureOffset3]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName3]
StringIndex=2
Substitute="":"0"

[MeasureOffsetString3]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName3]
StringIndex=3
Substitute="UTC":"GMT"

[MeasureTime3]
Measure=Time
Format=%a %#I:%M
TimeZone=([MeasureOffset3]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

[MeasureAMPM3]
Measure=Time
Format=%p
TimeZone=([MeasureOffset3]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

; Location4
[MeasureName4]
Measure=Plugin
Plugin=Plugins\WebParser.dll
UpdateRate=600
Url="http://time.yandex.com/sync.json?lang=en&geo=#Location4#"
Debug=1
RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
StringIndex=1
DecodeCharacterReference=1
DynamicVariables=1
Substitute="":"Updating.Yandex"
Disabled=1
FinishAction=[!EnableMeasure MeasureName5][!UpdateMeasure MeasureName5]

[MeasureOffset4]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName4]
StringIndex=2
Substitute="":"0"

[MeasureOffsetString4]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName4]
StringIndex=3
Substitute="UTC":"GMT"

[MeasureTime4]
Measure=Time
Format=%a %#I:%M
TimeZone=([MeasureOffset4]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

[MeasureAMPM4]
Measure=Time
Format=%p
TimeZone=([MeasureOffset4]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

; Location5
[MeasureName5]
Measure=Plugin
Plugin=Plugins\WebParser.dll
UpdateRate=600
Url="http://time.yandex.com/sync.json?lang=en&geo=#Location5#"
Debug=1
RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
StringIndex=1
DecodeCharacterReference=1
DynamicVariables=1
Substitute="":"Updating.Yandex"
Disabled=1
;FinishAction=[!EnableMeasure MeasureName6][!UpdateMeasure MeasureName6]

[MeasureOffset5]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName5]
StringIndex=2
Substitute="":"0"

[MeasureOffsetString5]
Measure=Plugin
Plugin=Plugins\WebParser.dll
Url=[MeasureName5]
StringIndex=3
Substitute="UTC":"GMT"

[MeasureTime5]
Measure=Time
Format=%a %#I:%M
TimeZone=([MeasureOffset5]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

[MeasureAMPM5]
Measure=Time
Format=%p
TimeZone=([MeasureOffset5]/3600000)
DaylightSavingTime=0
FormatLocale=local
DynamicVariables=1

; ; Location6
; [MeasureName6]
; Measure=Plugin
; Plugin=Plugins\WebParser.dll
; UpdateRate=600
; Url="http://time.yandex.com/sync.json?lang=en&geo=#Location6#"
; Debug=1
; RegExp="(?siU).*"name":"(.*)".*"offset":(.*),"offsetString":"(.*)""
; StringIndex=1
; DecodeCharacterReference=1
; DynamicVariables=1
; Substitute="":"Updating.Yandex"
; Disabled=1

; [MeasureOffset6]
; Measure=Plugin
; Plugin=Plugins\WebParser.dll
; Url=[MeasureName6]
; StringIndex=2
; Substitute="":"0"

; [MeasureOffsetString6]
; Measure=Plugin
; Plugin=Plugins\WebParser.dll
; Url=[MeasureName6]
; StringIndex=3
; Substitute="UTC":"GMT"

; [MeasureTime6]
; Measure=Time
; Format=%a %#I:%M
; TimeZone=([MeasureOffset6]/3600000)
; DaylightSavingTime=0
; FormatLocale=local
; DynamicVariables=1

; [MeasureAMPM6]
; Measure=Time
; Format=%p
; TimeZone=([MeasureOffset6]/3600000)
; DaylightSavingTime=0
; FormatLocale=local
; DynamicVariables=1

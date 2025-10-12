[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
Add-Type -AssemblyName System.Web -IgnoreWarnings

$app = '{6D809377-6AF0-444B-8957-A3773F02200E}\Rainmeter\Rainmeter.exe'
$notify = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app)

$ToastXml = New-Object -TypeName Windows.Data.Xml.Dom.XmlDocument

function EncodeVar {
  param([string]$name)
  $variableValue = $RmAPI.VariableStr($name)
  return [System.Web.HttpUtility]::HtmlEncode($variableValue)
}

function ToastIt {
  $TitleVar = EncodeVar('NotificationTitle')
  $ContextVar = EncodeVar('NotificationContext')
  $HeroImageVar = EncodeVar('NotificationTopImage')
  $appLogoOverrideVar = EncodeVar('NotificationIcon')
  $ButtonNameVar = EncodeVar('NotificationButtonName')
  $ButtonActionVar = EncodeVar('NotificationButtonAction')

  [xml]$ToastTemplate = @"
<toast launch="app-defined-string">
  <visual>
    <binding template="ToastGeneric">
      <text>$TitleVar</text>
      <text>$ContextVar</text>
      <image placement="hero" src="$HeroImageVar"/>
      <image placement="appLogoOverride" hint-crop="circle" src="$appLogoOverrideVar"/>
    </binding>
  </visual>
  <actions>
    <action content="$ButtonNameVar" arguments="$ButtonActionVar" activationType="protocol"/>
  </actions>
</toast>
"@

  $ToastXml.LoadXml($ToastTemplate.OuterXml)
  $notify.Show($ToastXml)
}

param([string]$Folder)
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $Folder | Out-Null
$phrases = [ordered]@{
  "c01" = "Jarvis turn on the lights"
  "c02" = "Hey Jarvis what is the weather like today"
  "c03" = "Jarvis play some jazz music"
  "c04" = "Okay Jarvis show me a three D model of a cat"
  "c05" = "Jarvis set a timer for ten minutes"
  "c06" = "Jarvis how tall is Mount Everest"
  "c07" = "Jarvis open Discord"
  "c08" = "Jarvis show off"
  "c09" = "Jarvis draw a house with a red roof on the board"
  "c10" = "Jarvis what time is it in Tokyo"
  "p01" = "Turn on the lights"
  "p02" = "What is the weather like today"
  "p03" = "Show me a three D model of a cat"
  "n00" = "Jarvis"
}
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($voice in ($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name } | Select-Object -First 2)) {
  $synth.SelectVoice($voice)
  foreach ($key in $phrases.Keys) {
    $path = Join-Path $Folder ("{0}__{1}.wav" -f $key, ($voice -replace '[^A-Za-z0-9]', ''))
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($phrases[$key])
    $synth.SetOutputToNull()
  }
}
$synth.Dispose()
Write-Output ("{0} clips" -f (Get-ChildItem $Folder -Filter *.wav).Count)

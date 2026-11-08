# Makes speech clips for tools\wake_eval.py with the Windows voices: files named real*.wav say the name, not*.wav do not.
# Usage: powershell -File tools\make_test_speech.ps1 <folder>
param([string]$Folder = "wake_clips")
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $Folder | Out-Null
$phrases = [ordered]@{
  "real1" = "Jarvis"
  "real2" = "Hey Jarvis, turn on the lights"
  "real3" = "Jarvis what is the weather today"
  "real4" = "Okay Jarvis set a timer for five minutes"
  "not01" = "Travis is serving dinner at the harvest festival"
  "not02" = "I have no service at the garage so I will get the car serviced"
  "not03" = "Let's go to the market and buy some carrots and garlic"
  "not04" = "The marvelous surgeon carved a perfect line and Charles was nervous"
  "not05" = "Can you turn on the lights in the kitchen please"
  "not06" = "So today we are going to demo the new project to the class"
  "not07" = "Please open the door and close the window it is cold in here"
  "not08" = "My name is Marcus and this is my friend Gervais from the service department"
  "not09" = "The weather today is sunny with a chance of rain in the evening"
  "not10" = "Yeah I think that is what he said but I am not sure about the details"
  "not11" = "Welcome everyone thank you for coming to our presentation this evening"
  "not12" = "Does anyone have questions about the hardware or the software"
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
Write-Output ("{0} clips in {1}" -f (Get-ChildItem $Folder -Filter *.wav).Count, $Folder)

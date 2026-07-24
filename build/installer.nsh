!macro customCheckAppRunning
  ; electron-builder's default GetProcessInfo macro crashes in System.dll
  ; when the installer itself is launched from a Unicode path. The app image
  ; name is sufficient here because it cannot match the installer process.
  ${nsProcess::FindProcess} "${APP_EXECUTABLE_FILENAME}" $R0
  ${If} $R0 == 0
    MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "Vibe Research is running. Close it before continuing." /SD IDOK IDOK closeRunningApp
    Quit
    closeRunningApp:
    ${nsProcess::CloseProcess} "${APP_EXECUTABLE_FILENAME}" $R0
    Sleep 1000
    ${nsProcess::FindProcess} "${APP_EXECUTABLE_FILENAME}" $R0
    ${If} $R0 == 0
      ${nsProcess::KillProcess} "${APP_EXECUTABLE_FILENAME}" $R0
      Sleep 300
    ${EndIf}
  ${EndIf}
  ${nsProcess::Unload}
!macroend

!macro customUnInstall
  ; Preserve by default; interactive users choose and silent deletion is explicit.
  StrCpy $R7 "0"
  ClearErrors
  ${GetParameters} $R8
  ${GetOptions} $R8 "--delete-app-data" $R9
  ${IfNot} ${Errors}
    StrCpy $R7 "1"
  ${ElseIfNot} ${Silent}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Delete Vibe Research projects, evidence, drafts, settings and cache? Choose No to keep data for reinstall." IDNO keepResearchData
    StrCpy $R7 "1"
    keepResearchData:
  ${EndIf}
  ${If} $R7 == "1"
    RMDir /r "$APPDATA\Vibe Research"
    RMDir /r "$APPDATA\VibeResearch"
    RMDir /r "$APPDATA\vibe-research"
  ${EndIf}
!macroend

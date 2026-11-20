; NSIS installer for WOWKISPICE - reproducible from tracked sources.
; Built by installer\build_installer.ps1 which stages all inputs first.
; Compile-time constants STAGING_DIR and VERSION are passed via makensis /D.

!ifndef STAGING_DIR
  !define STAGING_DIR "..\installer\build\staging"
!endif
!ifndef VERSION
  !define VERSION "0.1.0"
!endif

Name "WOWKISPICE"
OutFile "wowkispice_installer.exe"
InstallDir "$PROGRAMFILES\WOWKISPICE"
RequestExecutionLevel admin
ShowInstDetails show
SetCompressor /SOLID lzma

Page directory
Page instfiles

Var NgspicePresent

; -----------------------------------------
; Helper: registry keys (HKLM safe because RequestExecutionLevel=admin)
; -----------------------------------------
Section "Core Installation"
    SetOutPath "$INSTDIR"

    ; GUI executable (staged from source build)
    File "${STAGING_DIR}\wowkispice_gui.exe"

    ; CLI simulator (staged from cargo build)
    File "${STAGING_DIR}\wosp-cli.exe"

    ; Firmware controller DLL (optional - staged if present)
    !if /FILEEXISTS "${STAGING_DIR}\firmware_control.dll"
        File "${STAGING_DIR}\firmware_control.dll"
    !endif

    ; Self-check utility
    SetOutPath "$INSTDIR\tools"
    File "${STAGING_DIR}\run_selfcheck.bat"

    ; ngspice DLL (optional - staged if setup.ps1 fetched it)
    StrCpy $NgspicePresent "no"
    !if /FILEEXISTS "${STAGING_DIR}\tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll"
        SetOutPath "$INSTDIR\tools\ngspice_dll\Spice64_dll\dll-vs"
        File "${STAGING_DIR}\tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll"
        StrCpy $NgspicePresent "yes"
    !endif

    SetOutPath "$INSTDIR"

    ; Shortcuts
    CreateDirectory "$SMPROGRAMS\WOWKISPICE"
    CreateShortcut "$SMPROGRAMS\WOWKISPICE\WOWKISPICE GUI.lnk" "$INSTDIR\wowkispice_gui.exe"
    CreateShortcut "$SMPROGRAMS\WOWKISPICE\CLI Simulator.lnk" "$INSTDIR\wosp-cli.exe" "" "$INSTDIR\wosp-cli.exe"
    CreateShortcut "$SMPROGRAMS\WOWKISPICE\Run Self-Check.lnk" "$INSTDIR\tools\run_selfcheck.bat"

    ; Registry (audit + onboarding)
    WriteRegStr HKLM "SOFTWARE\WOWKISPICE" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "SOFTWARE\WOWKISPICE" "Version" "${VERSION}"
    WriteRegStr HKLM "SOFTWARE\WOWKISPICE" "NgspicePresent" "$NgspicePresent"
    WriteRegStr HKLM "SOFTWARE\WOWKISPICE" "SBOM" "CycloneDX 1.6 generated in CI; Julia backend pinned via bridge/julia/Manifest.toml"

    ; Uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\WOWKISPICE" "DisplayName" "WOWKISPICE"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\WOWKISPICE" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\WOWKISPICE" "DisplayVersion" "${VERSION}"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\wowkispice_gui.exe"
    Delete "$INSTDIR\wosp-cli.exe"
    Delete "$INSTDIR\firmware_control.dll"
    Delete "$INSTDIR\tools\run_selfcheck.bat"
    Delete "$INSTDIR\tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll"
    Delete "$INSTDIR\uninstall.exe"
    RMDir /r "$INSTDIR\tools"
    RMDir "$INSTDIR"
    Delete "$SMPROGRAMS\WOWKISPICE\WOWKISPICE GUI.lnk"
    Delete "$SMPROGRAMS\WOWKISPICE\CLI Simulator.lnk"
    Delete "$SMPROGRAMS\WOWKISPICE\Run Self-Check.lnk"
    RMDir "$SMPROGRAMS\WOWKISPICE"
    DeleteRegKey HKLM "SOFTWARE\WOWKISPICE"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\WOWKISPICE"
SectionEnd

Function .onInstSuccess
    MessageBox MB_OK "WOWKISPICE ${VERSION} installed successfully.$\r$\n$\r$\nStart Menu: WOWKISPICE$\r$\n  - GUI$\r$\n  - CLI Simulator$\r$\n  - Run Self-Check$\r$\n$\r$\nngspice bundled: $NgspicePresent"
FunctionEnd

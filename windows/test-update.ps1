$ErrorActionPreference = 'Stop'
$assemblyPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'
Add-Type -AssemblyName System.Web.Extensions
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
public static class UpdateTests {
    static Type checker, release;
    static BindingFlags flags=BindingFlags.Static|BindingFlags.Instance|BindingFlags.NonPublic;
    static object Call(string name, params object[] args) { return checker.GetMethod(name,flags).Invoke(null,args); }
    static void Assert(bool value,string message) { if(!value)throw new Exception(message); }
    static string Asset(string name,string url) { return "{\"name\":\""+name+"\",\"browser_download_url\":\""+url+"\"}"; }
    static string Release(string tag,bool draft,bool assets,bool valid) {
        string prefix=valid?"https://github.com/zeusu-sato/codex-usage-tray/releases/download/v1/":"https://evil.example/";
        string version=tag.Substring(1);
        return "{\"tag_name\":\""+tag+"\",\"draft\":"+(draft?"true":"false")+",\"prerelease\":true,\"assets\":["+(assets?Asset("CodexUsageTray-Setup-"+version+".exe",prefix+"setup")+","+Asset("SHA256SUMS.txt",prefix+"SHA256SUMS.txt"):"")+"]}";
    }
    static string version(object obj) { return (string)release.GetField("Version",flags).GetValue(obj); }
    public static void Run(string path) {
        var asm=Assembly.LoadFrom(path); checker=asm.GetType("UpdateCheck"); release=asm.GetType("UpdateRelease");
        Assert((int)Call("CompareVersions","1.0.0-beta.2","1.0.0-beta.11")<0,"numeric prerelease");
        Assert((int)Call("CompareVersions","1.0.0-beta","1.0.0")<0,"stable precedence");
        Assert((int)Call("CompareVersions","1.0.0-alpha","1.0.0-beta")<0,"ordinal precedence");
        string json="["+Release("v2.0.0",true,true,true)+","+Release("v1.9.0",false,false,true)+","+Release("v1.8.0",false,true,false)+","+Release("v1.7.0-beta.1",false,true,true)+","+Release("v1.0.0",false,true,true)+"]";
        object selected=Call("SelectRelease",json,"1.0.0"); Assert(version(selected)=="1.7.0-beta.1","selection");
        Assert(Call("SelectRelease",json,"1.7.0-beta.1")==null,"same and older");
        var request=(HttpWebRequest)Call("CreateRequest","https://example.invalid/");
        Assert(request.UserAgent=="CodexUsageTray" && request.Accept=="application/vnd.github+json" && request.Headers["Authorization"]==null && request.Headers["Cookie"]==null && request.CookieContainer==null && request.Credentials==null && (request.Proxy==null || request.Proxy.Credentials==null),"request privacy");
        int fetched=0,launched=0; string downloaded=null; bool match=true;
        Func<string,string> fetch=delegate(string url) { fetched++; throw new Exception("offline"); };
        Action<string,string> download=delegate(string url,string file) { downloaded=Path.GetDirectoryName(file); if(file.EndsWith(".exe")) File.WriteAllText(file,"fixture"); else { byte[] hash; using(var sha=SHA256.Create()) hash=sha.ComputeHash(Encoding.UTF8.GetBytes(match?"fixture":"other")); File.WriteAllText(file,BitConverter.ToString(hash).Replace("-","").ToLowerInvariant()+"  CodexUsageTray-Setup-1.7.0-beta.1.exe\n"); } };
        Action<string> launch=delegate(string file) { launched++; };
        object instance=Activator.CreateInstance(checker,flags,null,new object[]{fetch,download,launch},null);
        var check=checker.GetMethod("Check",flags); object[] args={null,null,null}; Assert((bool)check.Invoke(instance,args) && fetched==0,"development build");
        args=new object[]{"1.0.0",null,null}; Assert(!(bool)check.Invoke(instance,args) && fetched==1,"fetch failure");
        var install=checker.GetMethod("Install",flags); args=new object[]{selected,null}; Assert((bool)install.Invoke(instance,args) && launched==1,"matching hash"); Directory.Delete(downloaded,true);
        match=false; args=new object[]{selected,null}; Assert(!(bool)install.Invoke(instance,args) && launched==1 && !Directory.Exists(downloaded),"mismatching hash cleanup");
    }
}
'@
[UpdateTests]::Run([IO.Path]::GetFullPath($assemblyPath))
Write-Output 'PASS: update selection, request privacy, verification, cleanup, and failure handling.'

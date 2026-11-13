using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

internal sealed class UpdateRelease
{
    internal string Version, InstallerUrl, SumsUrl;
}

internal sealed class UpdateCheck
{
    internal const string ApiUrl = "https://api.github.com/repos/zeusu-sato/codex-usage-tray/releases?per_page=30";
    const string AssetPrefix = "https://github.com/zeusu-sato/codex-usage-tray/releases/download/";
    readonly Func<string, string> fetch;
    readonly Action<string, string> download;
    readonly Action<string> launch;
    internal UpdateCheck() : this(Fetch, Download, Launch) {}
    internal UpdateCheck(Func<string, string> fetch, Action<string, string> download, Action<string> launch)
    { this.fetch=fetch; this.download=download; this.launch=launch; }

    static string[] ParseVersion(string value)
    {
        if (value == null) return null;
        Match m=Regex.Match(value, @"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$");
        if (!m.Success) return null;
        string pre=m.Groups[4].Value;
        foreach(string part in pre.Split('.')) if(part.Length>1 && part[0]=='0' && Regex.IsMatch(part,@"^[0-9]+$")) return null;
        return new string[] { m.Groups[1].Value,m.Groups[2].Value,m.Groups[3].Value,pre };
    }
    static int NumberCompare(string a,string b) { int n=a.Length.CompareTo(b.Length); return n!=0?n:String.CompareOrdinal(a,b); }
    internal static int CompareVersions(string a,string b)
    {
        string[] x=ParseVersion(a), y=ParseVersion(b);
        if(x==null||y==null) throw new ArgumentException("Invalid version");
        for(int i=0;i<3;i++){int n=NumberCompare(x[i],y[i]);if(n!=0)return n;}
        if(x[3].Length==0||y[3].Length==0) return x[3].Length==y[3].Length?0:(x[3].Length==0?1:-1);
        string[] p=x[3].Split('.'),q=y[3].Split('.');
        for(int i=0;i<Math.Min(p.Length,q.Length);i++) {
            bool pn=Regex.IsMatch(p[i],@"^[0-9]+$"), qn=Regex.IsMatch(q[i],@"^[0-9]+$");
            int n=pn&&qn?NumberCompare(p[i],q[i]):pn!=qn?(pn?-1:1):String.CompareOrdinal(p[i],q[i]);
            if(n!=0)return n;
        }
        return p.Length.CompareTo(q.Length);
    }
    static string Field(IDictionary<string,object> obj,string name) { object value; return obj.TryGetValue(name,out value)?value as string:null; }
    static bool ValidUrl(string url) { Uri uri; return url!=null && url.StartsWith(AssetPrefix,StringComparison.Ordinal) && Uri.TryCreate(url,UriKind.Absolute,out uri) && uri.Scheme==Uri.UriSchemeHttps && uri.Host=="github.com" && uri.UserInfo.Length==0 && uri.Port==443 && uri.AbsoluteUri.StartsWith(AssetPrefix,StringComparison.Ordinal); }
    internal static UpdateRelease SelectRelease(string json,string current)
    {
        if(ParseVersion(current)==null) return null;
        var serializer=new JavaScriptSerializer(); serializer.MaxJsonLength=4*1024*1024;
        var list=serializer.DeserializeObject(json) as object[];
        if(list==null) throw new FormatException("Invalid release response");
        UpdateRelease best=null;
        foreach(object item in list) {
            var release=item as IDictionary<string,object>; if(release==null) continue;
            object draft; if(release.TryGetValue("draft",out draft) && draft is bool && (bool)draft) continue;
            string tag=Field(release,"tag_name"); if(ParseVersion(tag)==null || CompareVersions(tag,current)<=0 || (best!=null && CompareVersions(tag,best.Version)<=0)) continue;
            string version=tag.StartsWith("v",StringComparison.Ordinal)?tag.Substring(1):tag;
            string installer=null,sums=null; object assetsValue;
            if(!release.TryGetValue("assets",out assetsValue))continue;
            var assets=assetsValue as object[]; if(assets==null)continue;
            foreach(object assetValue in assets) { var asset=assetValue as IDictionary<string,object>; if(asset==null)continue;
                string name=Field(asset,"name"),url=Field(asset,"browser_download_url"); if(!ValidUrl(url))continue;
                if(name=="CodexUsageTray-Setup-"+version+".exe")installer=url;
                if(name=="SHA256SUMS.txt")sums=url;
            }
            if(installer!=null && sums!=null)best=new UpdateRelease { Version=version, InstallerUrl=installer, SumsUrl=sums };
        }
        return best;
    }
    internal static bool HashMatches(string sums,string filename,byte[] hash)
    {
        string expected=BitConverter.ToString(hash).Replace("-","").ToLowerInvariant();
        foreach(string line in sums.Split('\n')) { Match m=Regex.Match(line.TrimEnd('\r'),@"^([0-9a-f]{64})  (.+)$"); if(m.Success && m.Groups[2].Value==filename && m.Groups[1].Value==expected)return true; }
        return false;
    }
    internal bool Check(string current,out UpdateRelease release,out string error)
    {
        release=null;error=null;
        if(ParseVersion(current)==null || Environment.GetEnvironmentVariable("CODEX_USAGE_TRAY_UPDATE_CHECK")=="0")return true;
        try { release=SelectRelease(fetch(ApiUrl),current); return true; } catch(Exception ex) { error=ex.Message; return false; }
    }
    internal bool Install(UpdateRelease release,out string error)
    {
        error=null; string folder=Path.Combine(Path.GetTempPath(),"CodexUsageTray-update-"+Guid.NewGuid().ToString("N"));
        try {
            if(release==null || ParseVersion(release.Version)==null || !ValidUrl(release.InstallerUrl) || !ValidUrl(release.SumsUrl)) throw new InvalidOperationException("Invalid update");
            Directory.CreateDirectory(folder); string name="CodexUsageTray-Setup-"+release.Version+".exe", installer=Path.Combine(folder,name), sums=Path.Combine(folder,"SHA256SUMS.txt");
            download(release.InstallerUrl,installer); download(release.SumsUrl,sums);
            if(new FileInfo(installer).Length>300L*1024*1024 || new FileInfo(sums).Length>4*1024*1024)throw new InvalidDataException("Download too large");
            byte[] hash; using(var sha=SHA256.Create()) using(var stream=File.OpenRead(installer)) hash=sha.ComputeHash(stream);
            if(!HashMatches(File.ReadAllText(sums),name,hash))throw new InvalidDataException("SHA256 mismatch");
            launch(installer); return true;
        } catch(Exception ex) { error=ex.Message; try { if(Directory.Exists(folder))Directory.Delete(folder,true); } catch {} return false; }
    }
    internal static HttpWebRequest CreateRequest(string url)
    {
        ServicePointManager.SecurityProtocol |= (SecurityProtocolType)3072;
        var request=(HttpWebRequest)WebRequest.Create(url); request.Method="GET"; request.UserAgent="CodexUsageTray"; request.Accept="application/vnd.github+json";
        request.Timeout=15000; request.ReadWriteTimeout=15000; request.AllowAutoRedirect=false; request.CookieContainer=null; request.Credentials=null;
        if(request.Proxy!=null) request.Proxy.Credentials=null;
        return request;
    }
    static void CopyResponse(string url,Stream output,long limit)
    {
        for(int redirects=0;redirects<10;redirects++) {
            var request=CreateRequest(url);
            using(var response=(HttpWebResponse)request.GetResponse()) {
                if((int)response.StatusCode>=300 && (int)response.StatusCode<400) { Uri next=new Uri(new Uri(url),response.Headers["Location"]); if(next.Scheme!=Uri.UriSchemeHttps)throw new InvalidDataException("Insecure redirect"); url=next.AbsoluteUri; continue; }
                if(response.ContentLength>limit)throw new InvalidDataException("Response too large");
                using(var input=response.GetResponseStream()) { byte[] buffer=new byte[32768]; long total=0; int n; while((n=input.Read(buffer,0,buffer.Length))>0) { total+=n;if(total>limit)throw new InvalidDataException("Response too large");output.Write(buffer,0,n); } } return;
            }
        }
        throw new InvalidDataException("Too many redirects");
    }
    static string Fetch(string url) { using(var stream=new MemoryStream()) { CopyResponse(url,stream,4*1024*1024); return Encoding.UTF8.GetString(stream.ToArray()); } }
    static void Download(string url,string path) { using(var stream=File.Create(path)) CopyResponse(url,stream,path.EndsWith("SHA256SUMS.txt",StringComparison.Ordinal)?4*1024*1024:300L*1024*1024); }
    static void Launch(string path) { if(Process.Start(path,"/SILENT /SUPPRESSMSGBOXES /NORESTART")==null)throw new InvalidOperationException("Installer did not start"); }
}

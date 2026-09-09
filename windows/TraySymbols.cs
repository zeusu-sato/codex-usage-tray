using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

internal static class TraySymbols
{
    // Provider marks come from the user's official extensions; none are redistributed.
    static readonly Dictionary<string,Bitmap> symbols = new Dictionary<string,Bitmap>();
    const float SymbolOpacity = 0.18F;

    static Bitmap Symbol(string provider)
    {
        if(symbols.ContainsKey(provider))return symbols[provider];
        Bitmap result=null;
        string home=Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        foreach(string editor in new string[]{".vscode-insiders",".vscode"})
        {
            try
            {
                string root=Path.GetFullPath(Path.Combine(home,editor,"extensions"));
                string index=Path.Combine(root,"extensions.json");
                if(!File.Exists(index))continue;
                var rows=new JavaScriptSerializer().DeserializeObject(File.ReadAllText(index)) as IEnumerable;
                if(rows==null)continue;
                string id=provider=="claude"?"anthropic.claude-code":"openai.chatgpt";
                foreach(object row in rows)
                {
                    var item=row as Dictionary<string,object>;if(item==null)continue;
                    object identifier,relative;
                    if(!item.TryGetValue("identifier",out identifier)||!item.TryGetValue("relativeLocation",out relative))continue;
                    var named=identifier as Dictionary<string,object>;
                    if(named==null||!named.ContainsKey("id")||Convert.ToString(named["id"])!=id)continue;
                    string name=relative as string;
                    if(String.IsNullOrEmpty(name)||!name.StartsWith(id+"-",StringComparison.Ordinal)||Path.GetFileName(name)!=name)continue;
                    string extension=Path.GetFullPath(Path.Combine(root,name));
                    if(!String.Equals(Path.GetDirectoryName(extension),root,StringComparison.OrdinalIgnoreCase))continue;
                    string file=Path.Combine(extension,"resources",provider=="claude"?"claude-logo.png":"blossom.dark.png");
                    if(File.Exists(file))result=WhiteMask(file);
                    break;
                }
                if(result!=null)break;
            }
            catch(IOException){}catch(UnauthorizedAccessException){}catch(ArgumentException){}catch(InvalidOperationException){}
        }
        symbols[provider]=result;
        return result;
    }

    static Bitmap WhiteMask(string file)
    {
        using(var source=new Bitmap(file))
        {
            if(source.Width>1024||source.Height>1024)return null;
            using(var mask=new Bitmap(source.Width,source.Height,PixelFormat.Format32bppArgb))
            {
                int left=source.Width,top=source.Height,right=-1,bottom=-1;
                for(int y=0;y<source.Height;y++)for(int x=0;x<source.Width;x++)
                {
                    Color c=source.GetPixel(x,y);
                    // Extract only the light symbol, excluding the Claude orange app tile.
                    int brightness=Math.Min(c.R,Math.Min(c.G,c.B));
                    int alpha=(int)(c.A*Math.Max(0,Math.Min(1,(brightness-190)/55.0)));
                    mask.SetPixel(x,y,Color.FromArgb(alpha,255,255,255));
                    if(alpha>0){left=Math.Min(left,x);top=Math.Min(top,y);right=Math.Max(right,x);bottom=Math.Max(bottom,y);}
                }
                if(right<left)return null;
                return mask.Clone(Rectangle.FromLTRB(left,top,right+1,bottom+1),PixelFormat.Format32bppArgb);
            }
        }
    }

    internal static Icon Create(double? remaining,Color background,string provider)
    {
        using(var bitmap=new Bitmap(32,32,PixelFormat.Format32bppArgb))
        using(var g=Graphics.FromImage(bitmap))
        using(var fill=new SolidBrush(background))
        using(var format=new StringFormat(StringFormat.GenericTypographic))
        using(var font=new Font("Segoe UI",remaining==100?17F:22F,FontStyle.Bold,GraphicsUnit.Pixel))
        {
            g.Clear(background);
            Bitmap symbol=Symbol(provider);
            if(symbol!=null)
            {
                using(var attributes=new ImageAttributes())
                {
                    var matrix=new ColorMatrix();matrix.Matrix33=SymbolOpacity;attributes.SetColorMatrix(matrix);
                    float scale=Math.Min(30F/symbol.Width,30F/symbol.Height);
                    int width=(int)Math.Round(symbol.Width*scale),height=(int)Math.Round(symbol.Height*scale);
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.DrawImage(symbol,new Rectangle((32-width)/2,(32-height)/2,width,height),0,0,symbol.Width,symbol.Height,GraphicsUnit.Pixel,attributes);
                }
            }
            string value=remaining.HasValue?Math.Floor(remaining.Value).ToString(CultureInfo.InvariantCulture):"?";
            format.Alignment=StringAlignment.Center;format.LineAlignment=StringAlignment.Center;
            using(var letters=new GraphicsPath())
            using(var outline=new Pen(Color.FromArgb(190,5,18,16),1.4F))
            {
                // A fixed layout rectangle can suppress the entire line at tray sizes.
                // Build glyphs without a height limit, then center their visible bounds.
                letters.AddString(value,font.FontFamily,(int)FontStyle.Bold,font.Size,new PointF(0,0),StringFormat.GenericTypographic);
                RectangleF bounds=letters.GetBounds();
                using(var placement=new Matrix())
                {
                    placement.Translate((32-bounds.Width)/2-bounds.Left,(26-bounds.Height)/2-bounds.Top);
                    letters.Transform(placement);
                }
                g.SmoothingMode=SmoothingMode.AntiAlias;
                outline.LineJoin=LineJoin.Round;
                g.DrawPath(outline,letters);g.FillPath(Brushes.White,letters);
            }
            g.SmoothingMode=SmoothingMode.None;
            using(var track=new SolidBrush(Color.FromArgb(64,0,0,0)))g.FillRectangle(track,2,27,28,3);
            if(remaining.HasValue)g.FillRectangle(Brushes.White,2,27,(float)(28*remaining.Value/100),3);
            IntPtr handle=bitmap.GetHicon();
            try{using(var borrowed=Icon.FromHandle(handle))return (Icon)borrowed.Clone();}
            finally{DestroyIcon(handle);}
        }
    }
    [DllImport("user32.dll")]static extern bool DestroyIcon(IntPtr icon);
}

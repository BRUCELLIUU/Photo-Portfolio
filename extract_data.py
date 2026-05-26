"""Extract image metadata - with XMP support for PNG files."""
import json, os, sys, struct, traceback, io
import xml.etree.ElementTree as ET
from PIL import Image

BASE = r"C:\Users\25055\Desktop\个人摄影作品筛选"
CATS = ["风光","静物","人文"]
OUT = os.path.join(BASE, "image_data.json")

def extract_xmp_from_png(fpath):
    try:
        with open(fpath,'rb') as f:
            sig=f.read(8)
            if sig[:4]!=b'\x89PNG': return None
            while True:
                hdr=f.read(8)
                if len(hdr)<8: break
                length=struct.unpack('>I',hdr[:4])[0]
                ctype=hdr[4:8].decode('ascii',errors='replace')
                data=f.read(length); f.read(4)
                if ctype=='iTXt':
                    n1=data.find(b'\x00')
                    if n1<0: continue
                    kw=data[:n1].decode('utf-8',errors='replace')
                    if kw!='XML:com.adobe.xmp': continue
                    r=data[n1+1:]
                    r=r[2:]  # skip compression flag + method
                    n2=r.find(b'\x00')
                    if n2<0: continue
                    r=r[n2+1:]  # skip language tag
                    n3=r.find(b'\x00')
                    if n3<0: continue
                    xmp=r[n3+1:]  # text after translated keyword
                    root=ET.fromstring(xmp)
                    result={}
                    for desc in root.iter():
                        tag=desc.tag.split('}')[-1] if '}' in desc.tag else desc.tag
                        if tag!='Description': continue
                        m={
                            '{http://ns.adobe.com/tiff/1.0/}Make':'Make',
                            '{http://ns.adobe.com/tiff/1.0/}Model':'Model',
                            '{http://ns.adobe.com/exif/1.0/}DateTimeOriginal':'DateTimeOriginal',
                            '{http://ns.adobe.com/exif/1.0/}ExposureTime':'ExposureTime',
                            '{http://ns.adobe.com/exif/1.0/}FNumber':'FNumber',
                            '{http://ns.adobe.com/exif/1.0/}ISOSpeedRatings':'ISOSpeedRatings',
                            '{http://ns.adobe.com/exif/1.0/}FocalLength':'FocalLength',
                            '{http://ns.adobe.com/xap/1.0/}CreatorTool':'Software',
                        }
                        for ak,an in m.items():
                            v=desc.get(ak)
                            if v is not None: result[an]=v
                    return result if result else None
                if ctype=='IEND': break
    except Exception:
        sys.stderr.write(f"\n[XMP parse error] {fpath}: {traceback.format_exc()}\n")
    return None

def extract_exif(img):
    d=img._getexif()
    if not d: return None
    from PIL.ExifTags import TAGS
    r={}
    for tid,v in d.items():
        tn=TAGS.get(tid,str(tid))
        if tn in ("Make","Model","DateTimeOriginal","DateTime","ExposureTime","FNumber","ISOSpeedRatings","FocalLength","Software","Flash"):
            try:
                if isinstance(v,bytes): v=v.decode('utf-8',errors='replace').strip('\x00')
                if tn=='ExposureTime': r['ExposureTime']=float(v)
                elif tn=='FNumber': r['FNumber']=float(v)
                elif tn=='FocalLength': r['FocalLength']=float(v)
                elif tn=='ISOSpeedRatings': r['ISO']=int(v[0]) if isinstance(v,(list,tuple)) else int(v)
                else: r[tn]=str(v) if v is not None else ''
            except Exception:
                sys.stderr.write(f"\n[EXIF value parse error] tag={tn} value={v}: {traceback.format_exc()}\n")
    return r if r else None

def extract_colors(img):
    w,h=img.size; s=min(150/w,150/h); nw,nh=max(1,int(w*s)),max(1,int(h*s))
    sm=img.resize((nw,nh),Image.LANCZOS)
    if sm.mode!='RGB': sm=sm.convert('RGB')
    px=list(sm.getdata()); cm={}; qs=256//12
    for r,g,b in px:
        qr,qg,qb=r//qs,g//qs,b//qs
        k=(qr,qg,qb); cm[k]=cm.get(k,0)+1
    sc=sorted(cm.items(),key=lambda x:x[1],reverse=True)
    colors=[]
    for (qr,qg,qb),_ in sc:
        rr,gg,bb=qr*qs+qs//2,qg*qs+qs//2,qb*qs+qs//2
        if 25<0.299*rr+0.587*gg+0.114*bb<245:
            colors.append({"r":rr,"g":gg,"b":bb,"hex":f"#{rr:02x}{gg:02x}{bb:02x}"})
        if len(colors)>=3: break
    while len(colors)<3: colors.append({"r":80,"g":80,"b":80,"hex":"#505050"})
    return colors[:3]

def extract_tonal(img):
    if img.mode!='L': gray=img.convert('L')
    else: gray=img
    px=list(gray.getdata())
    if not px: return {"tonal":"中间调","contrast":"中等对比","avgLum":128,"histBins":[0]*32}
    hist=[0]*256; tl=0
    for p in px: hist[p]+=1; tl+=p
    al=tl/len(px); sd=sum(hist[:85]); mt=sum(hist[85:170]); hl=sum(hist[170:]); tp=sd+mt+hl
    tn='中间调'
    if al>170: tn='高调'
    elif al<85: tn='低调'
    elif tp>0 and abs(sd-hl)/tp<0.15 and 100<al<155: tn='均衡调'
    if tp>0:
        if sd/tp>0.4 and hl/tp>0.2: cn='高对比'
        elif sd/tp<0.15 and hl/tp<0.15: cn='低对比'
        else: cn='中等对比'
    else: cn='中等对比'
    bins=[sum(hist[i*8:(i+1)*8]) for i in range(32)]
    return {"tonal":tn,"contrast":cn,"avgLum":round(al),"histBins":bins}

def fmt_exif(exif):
    if not exif: return []
    rows=[]
    mp=[("Make","品牌"),("Model","型号"),("DateTimeOriginal","时间"),("ExposureTime","快门"),("FNumber","光圈"),("ISO","ISO"),("FocalLength","焦距"),("Software","软件")]
    for k,l in mp:
        if k not in exif: continue
        v=exif[k]
        try:
            if k=='ExposureTime': v=f"{v}s" if v>=1 else f"1/{round(1/v)}s"
            elif k=='FNumber': v=f"f/{round(v,1)}"
            elif k=='FocalLength': v=f"{round(v)}mm"
            else: v=str(v)
            rows.append([l,v])
        except: rows.append([l,str(v)])
    return rows

data={}; ok=0; err=0; dir_stats={}
for cat in CATS:
    cd=os.path.join(BASE,cat)
    if not os.path.isdir(cd): continue
    data[cat]=[]
    files=sorted([f for f in os.listdir(cd) if f.lower().endswith(('.jpg','.jpeg','.png'))])
    dir_stats[cat]=len(files)
    print(f"\n[{cat}] 目录：{len(files)} 张图片")
    for fn in files:
        fp=os.path.join(cd,fn)
        sys.stdout.write(f"\r{cat}/{fn:<30}"); sys.stdout.flush()
        try:
            img=Image.open(fp)
            exif=extract_exif(img)
            # For PNG, try XMP as fallback
            if not exif and fn.lower().endswith('.png'):
                xmp=extract_xmp_from_png(fp)
                if xmp:
                    # Convert XMP string values to proper types
                    for k in ('ExposureTime','FNumber','FocalLength'):
                        if k in xmp:
                            try:
                                # XMP stores rational as "num/den"
                                v=xmp[k]
                                if '/' in str(v):
                                    n,d=v.split('/'); xmp[k]=float(n)/float(d)
                                else: xmp[k]=float(v)
                            except Exception:
                                sys.stderr.write(f"\n[XMP float conv error] {fp}: {k}={xmp.get(k)}: {traceback.format_exc()}\n")
                    if 'ISOSpeedRatings' in xmp:
                        try: xmp['ISO']=int(xmp['ISOSpeedRatings'])
                        except Exception:
                            sys.stderr.write(f"\n[XMP ISO conv error] {fp}: ISOSpeedRatings={xmp.get('ISOSpeedRatings')}: {traceback.format_exc()}\n")
                    exif=xmp
            colors=extract_colors(img)
            tonal=extract_tonal(img)
            data[cat].append({"file":fn,"colors":colors,"tonal":tonal,"exif":fmt_exif(exif)})
            img.close(); ok+=1
        except Exception as e:
            sys.stderr.write(f"\n[ERROR] {cat}/{fn}: {e}\n")
            sys.stderr.write(traceback.format_exc())
            data[cat].append({"file":fn,"colors":[{"r":80,"g":80,"b":80,"hex":"#505050"}]*3,"tonal":{"tonal":"—","contrast":"—","avgLum":0,"histBins":[0]*32},"exif":[]})
            err+=1

total_scanned = sum(dir_stats.values())
print(f"\nDone: 目录 {dir_stats} → 共 {total_scanned} 张, {ok} ok, {err} err")
with open(OUT,"w",encoding="utf-8") as f:
    json.dump(data,f,ensure_ascii=False,indent=2)
print(f"Written to {OUT}")

# Also write image_meta.js for <script> tag loading (file:// compatible)
js_out = os.path.join(BASE, "image_meta.js")
with open(js_out, "w", encoding="utf-8") as f:
    f.write("window.IMAGE_META = ")
    json.dump(data, f, ensure_ascii=False)
    f.write(";\n")
print(f"Written to {js_out}")

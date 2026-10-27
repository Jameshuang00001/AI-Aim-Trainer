using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

// Opt-in Editor smoke test; does not ship in the player or invoke cloud analysis.
public static class OriginalArtVerification
{
    const string Request="Temp/OriginalArtVerify.request";
    const string Result="Temp/OriginalArtVerify.result";
    static int stage;
    static float next;
    static Target tracked;
    static Vector3 before;
    static string report="";
    [InitializeOnLoadMethod] static void Register()
    { EditorApplication.update-=Tick;EditorApplication.update+=Tick; }
    static void Assert(bool value,string message)
    { if(!value)throw new Exception(message);report+=message+": PASS\n"; }
    static Target Ready()
    {
        var targets=UnityEngine.Object.FindObjectsOfType<Target>().Where(t=>t.IsHittable).ToArray();
        Assert(targets.Length>0,"Eligible targets spawn");return targets[0];
    }
    static void CheckTarget(Target target)
    {
        var heads=target.GetComponentsInChildren<HitZone>().Where(z=>z.Zone==HitZoneType.Head).ToArray();
        Assert(heads.Length==1,"Exactly one head zone per dummy");
        Assert(heads[0].TargetParent==target,"Head resolves its Target owner");
        Assert(heads[0].GetComponent<Collider>().enabled && heads[0].GetComponent<Collider>().isTrigger,"Head trigger is enabled");
        Assert(target.GetComponentsInChildren<Renderer>().Length>=8,"Original dummy renders body and limbs");
        Assert(target.GetComponentInChildren<Animator>().runtimeAnimatorController!=null,"Original animation controller is present");
        var head=heads[0].GetComponent<Collider>();
        var ray=new Ray(head.bounds.center+Vector3.forward,Vector3.back);
        Assert(head.Raycast(ray,out RaycastHit hit,2f),"Head collider accepts an aimed ray");
    }
    static void Capture()
    {
        string path=File.ReadAllText(Request).Trim();Directory.CreateDirectory(Path.GetDirectoryName(path));
        var camera=Camera.main;var texture=new RenderTexture(1600,900,24);
        var headHeights=UnityEngine.Object.FindObjectsOfType<HitZone>().Where(z=>z.Zone==HitZoneType.Head).Select(z=>z.GetComponent<Collider>().bounds.center.y).ToArray();
        File.WriteAllText(Path.ChangeExtension(path,"heights.txt"),"Camera eye height: "+camera.transform.position.y+"\nTarget head heights: "+string.Join(", ",headHeights));
        var old=camera.targetTexture;var active=RenderTexture.active;float aspect=camera.aspect;
        var overlays=UnityEngine.Object.FindObjectsOfType<Canvas>().Where(c=>c.renderMode==RenderMode.ScreenSpaceOverlay).ToArray();
        var planes=overlays.Select(c=>c.planeDistance).ToArray();
        try {
            camera.targetTexture=texture;camera.aspect=1600f/900;
            foreach(var canvas in overlays){canvas.renderMode=RenderMode.ScreenSpaceCamera;canvas.worldCamera=camera;canvas.planeDistance=camera.nearClipPlane+.01f;}
            Canvas.ForceUpdateCanvases();camera.Render();RenderTexture.active=texture;
            var pixels=new Texture2D(1600,900,TextureFormat.RGB24,false);pixels.ReadPixels(new Rect(0,0,1600,900),0,0);pixels.Apply();
            File.WriteAllBytes(path,pixels.EncodeToPNG());UnityEngine.Object.DestroyImmediate(pixels);
        } finally {
            for(int i=0;i<overlays.Length;i++){overlays[i].renderMode=RenderMode.ScreenSpaceOverlay;overlays[i].worldCamera=null;overlays[i].planeDistance=planes[i];}
            camera.targetTexture=old;camera.aspect=aspect;RenderTexture.active=active;texture.Release();UnityEngine.Object.DestroyImmediate(texture);
        }
    }
    static void Finish(string text)
    { File.WriteAllText(Result,text);File.Delete(Request);EditorApplication.isPlaying=false;stage=0; }
    static void Tick()
    {
        if(!File.Exists(Request)||EditorApplication.isCompiling||EditorApplication.isUpdating)return;
        if(!EditorApplication.isPlaying){if(!EditorApplication.isPlayingOrWillChangePlaymode)EditorApplication.isPlaying=true;return;}
        if(GameModeManager.Instance==null||SessionManager.Instance==null)return;
        try {
            if(stage==0){report="";GameModeManager.Instance.StartGame();next=Time.realtimeSinceStartup+8;stage=1;return;}
            if(Time.realtimeSinceStartup<next)return;
            if(stage==1){var t=Ready();CheckTarget(t);Capture();int hits=ScoreManager.Instance.Hits;Assert(t.TryHit(HitZoneType.Head),"Head hit accepted");Assert(ScoreManager.Instance.Hits==hits+1,"Head hit updates score");GameModeManager.Instance.SetMovingTargetsMode();next=Time.realtimeSinceStartup+5;stage=2;return;}
            if(stage==2){tracked=Ready();CheckTarget(tracked);before=tracked.transform.position;next=Time.realtimeSinceStartup+2;stage=3;return;}
            if(stage==3){Assert(tracked!=null&&(tracked.transform.position-before).sqrMagnitude>.0001f,"Moving dummy changes position");GameModeManager.Instance.SetFlickTargetsMode();next=Time.realtimeSinceStartup+4;stage=4;return;}
            if(stage==4){var t=Ready();Assert(t.TryHit(HitZoneType.Body),"Flick target body hit accepted");next=Time.realtimeSinceStartup+1;stage=5;return;}
            if(stage==5){Ready();Assert(true,"Flick replacement spawns");GameModeManager.Instance.SetReactionTargetsMode();next=Time.realtimeSinceStartup+8;stage=6;return;}
            if(stage==6){var t=Ready();CheckTarget(t);Assert(t.TryHit(HitZoneType.Head),"Reaction target activates and accepts head hit");Finish("Success\n"+report);}
        }catch(Exception e){Debug.LogException(e);Finish("FAILED\n"+report+e);}
    }
}

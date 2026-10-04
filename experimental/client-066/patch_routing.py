"""Exact-shape, fail-closed transforms for the Windows 0.66.0 desktop client.

Only short anchors are distributed, not vendor source or binaries. The original
0.66.0 roster implementation is preserved, including automation bookkeeping.
"""
from pathlib import Path

RESTART_MARK = 'grok-switch-client-066-v1'
PROFILE_FIELD = 'grokSwitchLocalProfileDir'


def replace_once(source, before, after):
    count = source.count(before)
    if count != 1:
        raise ValueError(f'unknown or ambiguous 0.66.0 anchor ({count}): {before[:100]}')
    return source.replace(before, after, 1)


MAIN_ANCHOR = ('processConfig:{appVersion:Tw().version,isPackaged:Te.app.isPackaged,'
               'dataDir:(0,Lc.getSandRootDir)()},artifactPath:B1e()')
MAIN_PATCHED = ('processConfig:{appVersion:Tw().version,isPackaged:Te.app.isPackaged,'
                'dataDir:(0,Lc.getSandRootDir)(),grokSwitchLocalProfileDir:Te.app.getPath("userData")},'
                'artifactPath:B1e()')


def patch_client_routing_profile(source):
    if PROFILE_FIELD in source or RESTART_MARK in source:
        raise ValueError('client already contains a local routing patch; supply the original installation')
    return replace_once(source, MAIN_ANCHOR, MAIN_PATCHED)


COORDINATOR_REPLACEMENTS = [
    ('bootstrap:{processConfig:{appVersion:t,isPackaged:n,dataDir:s}}',
     'bootstrap:{processConfig:{appVersion:t,isPackaged:n,dataDir:s,'
     '...(typeof r.processConfig.grokSwitchLocalProfileDir==="string"?'
     '{grokSwitchLocalProfileDir:r.processConfig.grokSwitchLocalProfileDir}:{})}}'),
    ('function YB(){let r=new Map,e=new Set,t=new Set,n;return{requiredAgents:e,harnessOf:s=>r.get(s),',
     'function YB(__gsProfileDir){let __gsLocal=__gs066ReadAllowlist(__gsProfileDir),'
     'r=new Map([...__gsLocal].map(id=>[id,"box"])),e=new Set,t=new Set,n;return{'
     '__gsOwnsLocal:s=>__gsLocal.has(s),requiredAgents:e,harnessOf:s=>__gsLocal.has(s)?"box":r.get(s),'),
    ('let d=l.id,p=B1({raw:l.harness,previous:r.get(d)});r.set(d,p),',
     'let d=l.id,p=__gsLocal.has(d)?"box":B1({raw:l.harness,previous:r.get(d)});r.set(d,p),'),
    ('gatewayTranscript({payload:s,legacyServerActive:a}){if(a)return null;if(!N(s))return s;',
     'gatewayTranscript({payload:s,legacyServerActive:a}){if(!N(s))return a?null:s;'),
    ('let l=i??n,d=[...r.values()].some(f=>f!=="box");',
     'let l=i??n;if(a&&!__gsLocal.has(l))return null;let d=[...r.values()].some(f=>f!=="box");'),
    ('let f=YB(),g=new Set,',
     'let f=YB(t.processConfig.grokSwitchLocalProfileDir),g=new Set,'),
    ('acceptsAgent:({agentId:_})=>f.harnessOf(_)!=="unsupported"',
     'acceptsAgent:({agentId:_})=>!f.__gsOwnsLocal(_)&&f.harnessOf(_)!=="unsupported"'),
    ('be.isActive({agentId:G.id})?It({method:_,read:G,signal:te,demand:ce,gatewayReply:pe})',
     '!f.__gsOwnsLocal(G.id)&&be.isActive({agentId:G.id})?It({method:_,read:G,signal:te,demand:ce,gatewayReply:pe})'),
    ('be.isActive({agentId:G.id})?It({method:_,read:G,signal:te,demand:ce}):pt(',
     '!f.__gsOwnsLocal(G.id)&&be.isActive({agentId:G.id})?It({method:_,read:G,signal:te,demand:ce}):pt('),
    ('return UN(G)?(be.noteMountedAgent(G),{status:"ok",value:null})',
     'return UN(G)?(f.__gsOwnsLocal(G.id)||be.noteMountedAgent(G),{status:"ok",value:null})'),
]


def patch_coordinator(source):
    if '__gs066' in source or PROFILE_FIELD in source or RESTART_MARK in source:
        raise ValueError('coordinator already contains a local routing patch; supply the original installation')
    for before, after in COORDINATOR_REPLACEMENTS:
        source = replace_once(source, before, after)
    runtime = Path(__file__).with_name('local-routing.cjs').read_text(encoding='utf8')
    return replace_once(source, 'function YB(__gsProfileDir){',
                        f'/* {RESTART_MARK} */\n{runtime}\nfunction YB(__gsProfileDir){{')

"""Exercise the staged installation's actual routing functions with inert stubs.

Application modules are never loaded. Only the exact small roster/mux regions
are evaluated inside an isolated Node VM with fake filesystem and transports.
No application source is written or included in the repository.
"""
import argparse
import json
import subprocess
from pathlib import Path

from asar import load_archive, payload_of, walk
from verify_client import verify


def region(source, head, tail):
    if source.count(head) != 1 or source.count(tail) != 1:
        raise ValueError('ambiguous exercise source anchors')
    start, end = source.index(head), source.index(tail)
    if end <= start:
        raise ValueError('invalid exercise source anchor order')
    return source[start:end]


def exercise(install_dir, staged_dir):
    checked = verify(install_dir, staged_dir)
    if not checked['healthy']:
        raise ValueError('candidate verification failed')
    raw, header, start, _ = load_archive(Path(staged_dir) / 'app.asar')
    source = payload_of(raw, start, dict(walk(header))['dist/node-agent-coordinator/main.cjs']).decode('utf8')
    chunks = {
        'roster': region(source, 'function B1({raw:r,previous:e})', 'var AR=require("node:crypto");'),
        'mux': region(source, 'function KD(r){', 'function WD(r){'),
        'reads': region(source, 'pt=async({method:_,read:G,signal:te,demand:ce})', ',Se=DR('),
    }
    script = r'''
const assert = require('node:assert/strict'), vm = require('node:vm');
const chunks = CHUNKS;
const LOCAL = '11111111-1111-4111-8111-111111111111';
const REMOTE = '22222222-2222-4222-8222-222222222222';
const UNKNOWN = '33333333-3333-4333-8333-333333333333';
let config = {version:1,hostVersion:'1494ebd',agentIds:[LOCAL]}, checks = 0;
const ok = (actual,expected) => { assert.deepEqual(JSON.parse(JSON.stringify(actual)),expected); checks++; };
const fakeFs = { lstatSync:()=>({isFile:()=>true,isSymbolicLink:()=>false,size:100}),
  readFileSync:()=>JSON.stringify(config) };
const context = { require:n=>n==='node:fs'?fakeFs:require(n),
  N:x=>x!==null&&typeof x==='object'&&!Array.isArray(x) };
const makeRoster = vm.runInNewContext(chunks.roster+';YB', context);
const route = makeRoster('/profile');
ok(route.harnessOf(LOCAL),'box');
ok(route.noteRoster({agents:[{id:LOCAL,harness:'temporal'},{id:REMOTE,harness:'temporal'}]}),
   {addedTemporal:true,staleBoxAutomations:[]});
ok(route.harnessOf(LOCAL),'box'); ok(route.harnessOf(REMOTE),'temporal');
ok([...route.requiredAgents],[REMOTE]);
const event = id=>({type:'appended',agentId:id,entry:{id:'synthetic'}});
ok(route.gatewayTranscript({payload:event(LOCAL),legacyServerActive:true}),event(LOCAL));
ok(route.gatewayTranscript({payload:event(REMOTE),legacyServerActive:true}),null);
ok(route.gatewayTranscript({payload:event(UNKNOWN),legacyServerActive:true}),null);
ok(route.gatewayTranscript({payload:{type:'appended'},legacyServerActive:true}),null);
route.noteGatewaySession({payload:{activeAgentId:LOCAL}});
ok(route.gatewayTranscript({payload:{type:'appended'},legacyServerActive:true}),{type:'appended',agentId:LOCAL});
ok(route.gatewayTranscript({payload:{type:'snapshot',activeAgentId:REMOTE},legacyServerActive:true}),null);
ok(route.gatewayTranscript({payload:{type:'snapshot',activeAgentId:LOCAL},legacyServerActive:true}),{type:'snapshot',activeAgentId:LOCAL});
config = null;
const native = makeRoster('/profile');
native.noteRoster({agents:[{id:LOCAL,harness:'temporal'}]});
ok(native.harnessOf(LOCAL),'temporal');
const calls=[];
const gateway={dispatchCommand:async(method,args)=>{calls.push(['gateway',method,args.agentId??args.id]);return {accepted:true};}};
const control={getMachineId:async()=>null,isOnePasswordAppInstalled:async()=>false};
const KD = vm.runInNewContext(chunks.mux+';KD', {
  ve:()=>({}),N9:1000,BD:1000,ue:String,
  D9:(m,a)=>a.agentId??a.id,Dy:()=>true,j9:(m,a)=>({method:m,args:a}),
  BB:()=>({mirrorGateway:false}),PB:()=>false,VD:w=>w.args.agentId??w.args.id,
  Co:()=>undefined,yn:async({request})=>{calls.push(['server',request.method,request.args.agentId]);return {status:'ok',value:{accepted:true}};},
  Ss:(m,r)=>r.value,U9:()=>false,he:Error,
});
const mux=KD({gateway,control,log:()=>{},clock:{now:()=>0},harnessOf:route.harnessOf});
async function run(){
  await mux.dispatchCommand('sendPrompt',{agentId:LOCAL,text:'synthetic'});
  await mux.dispatchCommand('sendPrompt',{agentId:REMOTE,text:'synthetic'});
  ok(calls,[['gateway','sendPrompt',LOCAL],['server','sendPrompt',REMOTE]]);
  const reads=[];
  const readApi=vm.runInNewContext('let y,h;let '+chunks.reads+';({pt,Re})', {
    f:route,LN:()=>true,aS:'read-failed',
    be:{isActive:()=>true},
    De:async(method,args)=>{reads.push(['gateway',method,args.id]);return {status:'ok',value:{source:'gateway'}};},
    It:async({method,read})=>{reads.push(['server',method,read.id]);return {status:'ok',value:{source:'server'}};},
  });
  for(const method of ['openAgentTail','getAgentTranscriptTail']){
    ok(await readApi.Re(method,{id:LOCAL,limit:10}),{status:'ok',value:{source:'gateway'}});
    ok(await readApi.Re(method,{id:REMOTE,limit:10}),{status:'ok',value:{source:'server'}});
  }
  ok(reads,[['gateway','openAgentTail',LOCAL],['server','openAgentTail',REMOTE],
            ['gateway','getAgentTranscriptTail',LOCAL],['server','getAgentTranscriptTail',REMOTE]]);
  console.log(JSON.stringify({ok:true,checks,kind:'actual-staged-functions-with-inert-stubs',networkCalls:0}));
}
run().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''.replace('CHUNKS', json.dumps(chunks))
    result = subprocess.run(['node', '-'], input=script.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError('routing exercise failed: ' + result.stderr.decode('utf8', errors='replace')[-3000:])
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', required=True)
    parser.add_argument('--staged-dir', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(exercise(args.install_dir, args.staged_dir), indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, 'CLIENT-EXERCISE-FAILED: ' + str(error) + '\n')


if __name__ == '__main__':
    main()

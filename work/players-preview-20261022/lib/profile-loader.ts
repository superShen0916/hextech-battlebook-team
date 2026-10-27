import type {Profile} from '../src/App';
const cache=new Map<string,Promise<Profile>>();
export function loadProfile(profile:Profile):Promise<Profile>{
 if(!profile.has_detail)return Promise.resolve(profile);
 const url=profile.detail_url||`/api/profiles/${encodeURIComponent(profile.id)}.json`;
 const previous=cache.get(url);if(previous)return previous;
 const promise=fetch(url,{cache:profile.detail_url?'force-cache':'no-cache'})
  .then(async response=>{if(!response.ok)throw Error('detail_missing');const data=await response.json() as Profile;if(data.id!==profile.id||!Array.isArray(data.recent))throw Error('detail_mismatch');return {...profile,...data,history_scope:profile.history_scope};})
  .catch(error=>{cache.delete(url);throw error;});
 cache.set(url,promise);return promise;
}

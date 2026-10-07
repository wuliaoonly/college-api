let csrf = '';
export function setCsrf(value:string) { csrf=value; }
export async function api<T=any>(path:string, method='GET', body?:unknown):Promise<T> {
  const isForm=body instanceof FormData;
  const response=await fetch('/portal-api'+path,{method,credentials:'same-origin',headers:{...(body&&!isForm?{'Content-Type':'application/json'}:{}),...(method!=='GET'?{'X-CSRF-Token':csrf}:{})},body:body===undefined?undefined:isForm?body as FormData:JSON.stringify(body)});
  if(!response.ok){let message='服务暂时不可用，请稍后重试';try{message=(await response.json()).detail||message;}catch{}throw new Error(message);}
  if(response.headers.get('content-type')?.includes('application/zip'))return await response.blob() as T;
  return response.json();
}

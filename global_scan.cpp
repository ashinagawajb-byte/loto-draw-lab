// One-pass full-match scanner. For each seed calculate one LOTO6 and one LOTO7
// shuffle and compare them against ALL historical target rounds in memory.
// Usage: global_scan START COUNT TARGETS.tsv
// TSV rows: game TAB round TAB main CSV TAB bonus CSV
// stdout: game TAB round TAB seed TAB bonus_matched (when mode=main)
// By default stdout remains game TAB round TAB seed (complete main+bonus matches).
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

struct Key {
  uint64_t main, bonus;
  bool operator==(const Key& rhs) const { return main==rhs.main && bonus==rhs.bonus; }
};
struct KeyHash {
  size_t operator()(const Key& key) const {
    uint64_t x=key.main ^ (key.bonus*0x9e3779b97f4a7c15ULL);
    x^=x>>30; x*=0xbf58476d1ce4e5b9ULL;
    x^=x>>27; x*=0x94d049bb133111ebULL;
    return static_cast<size_t>(x^(x>>31));
  }
};
static std::vector<int> parse(const std::string& s){
  std::vector<int> nums; size_t pos=0;
  while(pos<s.size()){
    const auto end=s.find(',',pos);
    auto part=s.substr(pos,end==std::string::npos?std::string::npos:end-pos);
    size_t n=0;
    int value=std::stoi(part,&n);
    if(n!=part.size()) throw std::invalid_argument("invalid number");
    nums.push_back(value);
    if(end==std::string::npos)break;
    pos=end+1;
  }
  return nums;
}
static uint64_t mask(const std::vector<int>& vals,int count,int maxval){
  if(static_cast<int>(vals.size())!=count)throw std::invalid_argument("bad number count");
  uint64_t result=0;
  for(int v:vals){
    if(v<1||v>maxval)throw std::invalid_argument("number out of range");
    const uint64_t bit=uint64_t{1}<<v;
    if(result&bit)throw std::invalid_argument("duplicate");
    result|=bit;
  }
  return result;
}
static uint32_t rnd(uint32_t& state){
  state+=0x6D2B79F5u;
  uint32_t t=state;
  t=(t^(t>>15))*(t|1u);
  t^=t+((t^(t>>7))*(t|61u));
  return t^(t>>14);
}
static Key draw(int n,int k,int b,uint32_t seed){
  std::array<int,43> a{};
  for(int i=0;i<n;++i)a[i]=i+1;
  uint32_t state=seed;
  for(int i=n-1;i>0;--i){
    const uint32_t j=static_cast<uint32_t>((uint64_t{rnd(state)}*(i+1))>>32);
    std::swap(a[i],a[j]);
  }
  Key key{0,0};
  for(int i=0;i<k;++i)key.main|=uint64_t{1}<<a[i];
  for(int i=k;i<k+b;++i)key.bonus|=uint64_t{1}<<a[i];
  return key;
}
using Index=std::unordered_map<Key,std::vector<std::string>,KeyHash>;
using MainIndex=std::unordered_map<uint64_t,std::vector<std::pair<std::string,uint64_t>>>;
int main(int argc,char** argv){
  try{
    if(argc!=4 && argc!=5)throw std::invalid_argument("usage: global_scan START COUNT TARGETS.tsv [main]");
    const bool main_only=argc==5;
    if(main_only && std::string(argv[4])!="main")throw std::invalid_argument("invalid mode");
    size_t used=0;
    const std::string startstr=argv[1],countstr=argv[2];
    const uint64_t start=std::stoull(startstr,&used);
    if(used!=startstr.size()||start>= (uint64_t{1}<<32))throw std::invalid_argument("bad start");
    const uint64_t count=std::stoull(countstr,&used);
    if(used!=countstr.size()||count>(uint64_t{1}<<32)-start)throw std::invalid_argument("bad count");
    std::ifstream in(argv[3]);
    if(!in)throw std::runtime_error("targets file inaccessible");
    Index idx6,idx7;
    MainIndex main6,main7;
    std::string line;size_t entries=0;
    while(std::getline(in,line)){
      if(line.empty())continue;
      std::array<std::string,4> cols;
      size_t pos=0;
      for(int i=0;i<3;++i){
        const auto end=line.find('\t',pos);
        if(end==std::string::npos)throw std::invalid_argument("malformed TSV");
        cols[i]=line.substr(pos,end-pos);pos=end+1;
      }
      cols[3]=line.substr(pos);
      const bool six=cols[0]=="6";
      if(!six&&cols[0]!="7")throw std::invalid_argument("invalid game");
      const int n=six?43:37,k=six?6:7,b=six?1:2;
      const Key key{mask(parse(cols[2]),k,n),mask(parse(cols[3]),b,n)};
      if(key.main&key.bonus)throw std::invalid_argument("overlap");
      (six?idx6:idx7)[key].push_back(cols[1]);
      (six?main6:main7)[key.main].push_back({cols[1],key.bonus});
      ++entries;
    }
    if(entries==0)throw std::invalid_argument("missing targets");
    for(uint64_t offset=0;offset<count;++offset){
      const uint32_t seed=static_cast<uint32_t>(start+offset);
      const Key k6=idx6.empty()?Key{0,0}:draw(43,6,1,seed),k7=idx7.empty()?Key{0,0}:draw(37,7,2,seed);
      if(main_only){
        const auto a=main6.find(k6.main);
        if(a!=main6.end())for(const auto& target:a->second)
          std::cout<<"6\t"<<target.first<<"\t"<<seed<<"\t"<<(target.second==k6.bonus?1:0)<<"\n";
        const auto b=main7.find(k7.main);
        if(b!=main7.end())for(const auto& target:b->second)
          std::cout<<"7\t"<<target.first<<"\t"<<seed<<"\t"<<(target.second==k7.bonus?1:0)<<"\n";
      }else{
        const auto a=idx6.find(k6);
        if(a!=idx6.end())for(const auto& round:a->second)
          std::cout<<"6\t"<<round<<"\t"<<seed<<"\n";
        const auto b=idx7.find(k7);
        if(b!=idx7.end())for(const auto& round:b->second)
          std::cout<<"7\t"<<round<<"\t"<<seed<<"\n";
      }
    }
  }catch(const std::exception& ex){
    std::cerr<<"global_scan: "<<ex.what()<<"\n";return 2;
  }
}

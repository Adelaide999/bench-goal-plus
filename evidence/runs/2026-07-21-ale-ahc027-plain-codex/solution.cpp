#include <algorithm>
#include <chrono>
#include <climits>
#include <functional>
#include <iostream>
#include <numeric>
#include <queue>
#include <string>
#include <vector>
using namespace std;

static constexpr int INF = 1e9;
static constexpr int MAX_L = 100000;

int N, V;
vector<vector<int>> adj;
vector<vector<int>> dist_all;
vector<int> dirt;

int cell_id(int i, int j) { return i * N + j; }

void bfs_all_distances() {
    dist_all.assign(V, vector<int>(V, INF));
    queue<int> q;
    for (int s = 0; s < V; ++s) {
        auto &dist = dist_all[s];
        fill(dist.begin(), dist.end(), INF);
        while (!q.empty()) q.pop();
        q.push(s);
        dist[s] = 0;
        while (!q.empty()) {
            int u = q.front();
            q.pop();
            for (int v : adj[u]) {
                if (dist[v] > dist[u] + 1) {
                    dist[v] = dist[u] + 1;
                    q.push(v);
                }
            }
        }
    }
}

void build_bfs_tree(vector<int> &parent) {
    parent.assign(V, -1);
    vector<char> vis(V, 0);
    queue<int> q;
    q.push(0);
    vis[0] = 1;
    while (!q.empty()) {
        int u = q.front();
        q.pop();
        for (int v : adj[u]) {
            if (!vis[v]) {
                vis[v] = 1;
                parent[v] = u;
                q.push(v);
            }
        }
    }
}

vector<int> make_weighted_euler_walk(const vector<int> &parent) {
    vector<vector<int>> tree(V);
    for (int v = 1; v < V; ++v) {
        tree[parent[v]].push_back(v);
    }

    vector<int> subtree_size(V, 0);
    vector<long long> subtree_dirt(V, 0);

    function<void(int)> dfs = [&](int u) {
        subtree_size[u] = 1;
        subtree_dirt[u] = dirt[u];
        for (int v : tree[u]) {
            dfs(v);
            subtree_size[u] += subtree_size[v];
            subtree_dirt[u] += subtree_dirt[v];
        }
        sort(tree[u].begin(), tree[u].end(), [&](int a, int b) {
            long long lhs = subtree_dirt[a] * subtree_size[b];
            long long rhs = subtree_dirt[b] * subtree_size[a];
            if (lhs != rhs) return lhs > rhs;
            if (subtree_size[a] != subtree_size[b]) return subtree_size[a] < subtree_size[b];
            return a < b;
        });
    };
    dfs(0);

    vector<int> walk;
    walk.reserve(2 * V);
    walk.push_back(0);

    function<void(int)> euler = [&](int u) {
        for (int v : tree[u]) {
            walk.push_back(v);
            euler(v);
            walk.push_back(u);
        }
    };
    euler(0);
    return walk;
}

vector<int> shortest_path(int s, int t) {
    vector<int> par(V, -1);
    queue<int> q;
    q.push(s);
    par[s] = s;
    while (!q.empty()) {
        int u = q.front();
        q.pop();
        if (u == t) break;
        for (int v : adj[u]) {
            if (par[v] == -1) {
                par[v] = u;
                q.push(v);
            }
        }
    }

    vector<int> path;
    int cur = t;
    while (cur != s) {
        path.push_back(cur);
        cur = par[cur];
    }
    reverse(path.begin(), path.end());
    return path;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    cin >> N;
    V = N * N;
    vector<string> h(N - 1), v(N);
    for (int i = 0; i < N - 1; ++i) cin >> h[i];
    for (int i = 0; i < N; ++i) cin >> v[i];

    dirt.assign(V, 0);
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            cin >> dirt[cell_id(i, j)];
        }
    }

    adj.assign(V, {});
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            int id = cell_id(i, j);
            if (i + 1 < N && h[i][j] == '0') adj[id].push_back(cell_id(i + 1, j));
            if (i - 1 >= 0 && h[i - 1][j] == '0') adj[id].push_back(cell_id(i - 1, j));
            if (j + 1 < N && v[i][j] == '0') adj[id].push_back(cell_id(i, j + 1));
            if (j - 1 >= 0 && v[i][j - 1] == '0') adj[id].push_back(cell_id(i, j - 1));
        }
    }

    bfs_all_distances();

    vector<int> parent;
    build_bfs_tree(parent);
    vector<int> walk = make_weighted_euler_walk(parent);

    vector<int> cand(V);
    iota(cand.begin(), cand.end(), 0);
    sort(cand.begin(), cand.end(), [&](int a, int b) {
        if (dirt[a] != dirt[b]) return dirt[a] > dirt[b];
        return a < b;
    });
    const int CAND_LIMIT = min(V, 180);
    cand.resize(CAND_LIMIT);

    auto start = chrono::steady_clock::now();

    for (int iter = 0; iter < 250; ++iter) {
        if ((int)walk.size() - 1 >= MAX_L) break;
        auto elapsed = chrono::duration_cast<chrono::milliseconds>(chrono::steady_clock::now() - start).count();
        if (elapsed > 1700) break;

        int L = (int)walk.size() - 1; // cycle length in moves
        vector<vector<int>> occ(V);
        for (int t = 0; t < L; ++t) {
            occ[walk[t]].push_back(t);
        }

        long long best_score = -1;
        int best_target = -1;
        int best_mid = -1;
        int best_u = -1;

        for (int target : cand) {
            if (target == 0) continue;
            const auto &pos = occ[target];
            int m = (int)pos.size();
            if (m == 0) continue;
            for (int idx = 0; idx < m; ++idx) {
                int prev = pos[idx];
                int next = (idx + 1 < m ? pos[idx + 1] : pos[0] + L);
                int gap = next - prev;
                if (gap <= 2) continue;

                int mid = prev + gap / 2;
                if (mid >= L) mid -= L;
                int u = walk[mid];
                int duv = dist_all[u][target];
                if (duv <= 0 || duv >= INF) continue;
                if (L + 2 * duv > MAX_L) continue;

                int visit_time = prev + gap / 2 + duv;
                if (visit_time >= next) continue;

                int I1 = visit_time - prev;
                int I2 = next - visit_time;
                long long reduction = 1LL * gap * gap - 1LL * I1 * I1 - 1LL * I2 * I2;
                if (reduction <= 0) continue;

                long long score = 1LL * dirt[target] * reduction / (duv + 1);
                if (score > best_score) {
                    best_score = score;
                    best_target = target;
                    best_mid = mid;
                    best_u = u;
                }
            }
        }

        if (best_target == -1) break;

        vector<int> path = shortest_path(best_u, best_target);
        vector<int> insert_seq;
        insert_seq.reserve(path.size() * 2);
        for (int x : path) insert_seq.push_back(x);
        for (int i = (int)path.size() - 2; i >= 0; --i) insert_seq.push_back(path[i]);
        insert_seq.push_back(best_u);

        vector<int> new_walk;
        new_walk.reserve(walk.size() + insert_seq.size());
        for (int i = 0; i <= best_mid; ++i) new_walk.push_back(walk[i]);
        for (int x : insert_seq) new_walk.push_back(x);
        for (int i = best_mid + 1; i < (int)walk.size(); ++i) new_walk.push_back(walk[i]);
        walk.swap(new_walk);
    }

    string ans;
    ans.reserve(max(0, (int)walk.size() - 1));
    for (int i = 0; i + 1 < (int)walk.size(); ++i) {
        int cur = walk[i];
        int nxt = walk[i + 1];
        int ci = cur / N, cj = cur % N;
        int ni = nxt / N, nj = nxt % N;
        if (ni == ci + 1) ans.push_back('D');
        else if (ni == ci - 1) ans.push_back('U');
        else if (nj == cj + 1) ans.push_back('R');
        else if (nj == cj - 1) ans.push_back('L');
        else {
            // Should not happen if the route stays on the graph.
            return 0;
        }
    }

    cout << ans << '\n';
    return 0;
}

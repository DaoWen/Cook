;;
;; Copyright (c) Two Sigma Open Source, LLC
;;
;; Licensed under the Apache License, Version 2.0 (the "License");
;; you may not use this file except in compliance with the License.
;; You may obtain a copy of the License at
;;
;;  http://www.apache.org/licenses/LICENSE-2.0
;;
;; Unless required by applicable law or agreed to in writing, software
;; distributed under the License is distributed on an "AS IS" BASIS,
;; WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
;; See the License for the specific language governing permissions and
;; limitations under the License.
;;
(ns cook.test.mesos.sandbox
  (:use clojure.test)
  (:require [clj-http.client :as http]
            [clojure.core.cache :as cache]
            [clojure.string :as str]
            [cook.mesos.sandbox :as sandbox]
            [cook.test.testutil :as tu]
            [datomic.api :as d]
            [metrics.counters :as counters]
            [plumbing.core :as pc])
  (:import (java.util.concurrent CountDownLatch TimeUnit)))

(deftest test-agent->task-id->sandbox
  (let [task-id->sandbox-agent (agent {})]
    (send task-id->sandbox-agent sandbox/aggregate-sandbox "t0" "s0")
    (send task-id->sandbox-agent sandbox/aggregate-sandbox "t2" "s2")
    (send task-id->sandbox-agent sandbox/aggregate-sandbox "t3" "s3")
    (await task-id->sandbox-agent)

    (is (= "s0" (sandbox/agent->task-id->sandbox task-id->sandbox-agent "t0")))
    (is (nil? (sandbox/agent->task-id->sandbox task-id->sandbox-agent "t1")))
    (is (= "s2" (sandbox/agent->task-id->sandbox task-id->sandbox-agent "t2")))
    (is (= "s3" (sandbox/agent->task-id->sandbox task-id->sandbox-agent "t3")))
    (is (nil? (sandbox/agent->task-id->sandbox task-id->sandbox-agent "t4")))))

(defmacro assert-clear-agent-state-result
  [initial-state clear-data expected-state]
  `(let [task-id->sandbox-agent# (agent ~initial-state)]
     (counters/clear! sandbox/sandbox-aggregator-pending-count)
     (counters/inc! sandbox/sandbox-aggregator-pending-count (count ~initial-state))

     (send task-id->sandbox-agent# sandbox/clear-agent-state ~clear-data)
     (await task-id->sandbox-agent#)

     (is (= @task-id->sandbox-agent# ~expected-state))
     (is (= (counters/value sandbox/sandbox-aggregator-pending-count) (count ~expected-state)))))

(deftest test-clear-agent-state
  (assert-clear-agent-state-result nil nil nil)
  (assert-clear-agent-state-result nil {} nil)
  (assert-clear-agent-state-result nil {"a" 1} nil)

  (assert-clear-agent-state-result {} nil {})
  (assert-clear-agent-state-result {} {} {})
  (assert-clear-agent-state-result {"a" 1, "b" 2} {"a" 1, "b" 2} {})

  (assert-clear-agent-state-result {"a" 1} nil {"a" 1})
  (assert-clear-agent-state-result {"a" 1} {} {"a" 1})

  (assert-clear-agent-state-result {"a" 1, "b" 2} {"c" 3, "d" 4} {"a" 1, "b" 2})
  (assert-clear-agent-state-result {"a" 1, "b" 2, "c" 3, "d" 4} {"c" 3, "d" 4} {"a" 1, "b" 2}))

(defmacro assert-aggregate-sandbox-single
  [initial-state task-id sandbox expected-state]
  `(let [task-id->sandbox-agent# (agent ~initial-state)]
     (counters/clear! sandbox/sandbox-aggregator-pending-count)
     (counters/inc! sandbox/sandbox-aggregator-pending-count (count ~initial-state))

     (send task-id->sandbox-agent# sandbox/aggregate-sandbox ~task-id ~sandbox)
     (await task-id->sandbox-agent#)

     (is (= @task-id->sandbox-agent# ~expected-state))
     (is (= (counters/value sandbox/sandbox-aggregator-pending-count) (count ~expected-state)))))

(deftest test-aggregate-sandbox-single
  (assert-aggregate-sandbox-single {} "a" 1 {"a" 1})
  (assert-aggregate-sandbox-single {"a" 1} "a" 2 {"a" 1})
  (assert-aggregate-sandbox-single {"x" 7, "y" 8, "z" 9} "a" 1 {"a" 1, "x" 7, "y" 8, "z" 9}))

(defmacro assert-aggregate-sandbox-multiple
  [initial-state aggregate-data expected-state]
  `(let [task-id->sandbox-agent# (agent ~initial-state)]
     (counters/clear! sandbox/sandbox-aggregator-pending-count)
     (counters/inc! sandbox/sandbox-aggregator-pending-count (count ~initial-state))

     (send task-id->sandbox-agent# sandbox/aggregate-sandbox ~aggregate-data)
     (await task-id->sandbox-agent#)

     (is (= @task-id->sandbox-agent# ~expected-state))
     (is (= (counters/value sandbox/sandbox-aggregator-pending-count) (count ~expected-state)))))

(deftest test-aggregate-sandbox-multiple
  (assert-aggregate-sandbox-multiple {} {"a" 1} {"a" 1})
  (assert-aggregate-sandbox-multiple {} {"a" 1, "b" 2, "c" 2} {"a" 1, "b" 2, "c" 2})
  (assert-aggregate-sandbox-multiple {"a" 1} {"a" 2} {"a" 1})
  (assert-aggregate-sandbox-multiple {"x" 7, "y" 8} {"a" 1, "x" 7} {"a" 1, "x" 7, "y" 8})
  (assert-aggregate-sandbox-multiple {"x" 7, "y" 8} {"a" 1, "b" 2, "x" 7} {"a" 1, "b" 2, "x" 7, "y" 8})
  (assert-aggregate-sandbox-multiple {"x" 7, "y" 8, "z" 9} {"a" 1} {"a" 1, "x" 7, "y" 8, "z" 9}))

(defn- retrieve-sandbox
  [db-conn task-id]
  (let [datomic-db (d/db db-conn)]
    (-> (d/q '[:find ?s
               :in $ ?t
               :where
               [?e :instance/task-id ?t]
               [?e :instance/sandbox-directory ?s]]
             datomic-db task-id)
        ffirst)))

(deftest test-publish-sandbox-to-datomic!
  (let [db-conn (tu/restore-fresh-database! "datomic:mem://test-publish-sandbox-to-datomic!")]
    (testing "single entry"
      (let [num-tasks 20
            batch-size 4
            task-id->sandbox (pc/map-from-keys #(str "/sandbox/for/" %)
                                               (map #(str "exec-" %) (range num-tasks)))
            task-id->sandbox-in-db (pc/map-from-keys #(str "/sandbox/exists/" %)
                                                     (->> (keys task-id->sandbox)
                                                          (take 10)))
            task-id->sandbox-not-in-db (apply dissoc task-id->sandbox (keys task-id->sandbox-in-db))
            task-id->sandbox-agent (agent task-id->sandbox)]

        (doseq [[task-id _] task-id->sandbox-not-in-db]
          (tu/create-dummy-instance db-conn (tu/create-dummy-job db-conn) :task-id task-id))
        (doseq [[task-id sandbox] task-id->sandbox-in-db]
          (tu/create-dummy-instance db-conn (tu/create-dummy-job db-conn) :task-id task-id :sandbox-directory sandbox))

        (sandbox/publish-sandbox-to-datomic! db-conn batch-size task-id->sandbox-agent)
        (await task-id->sandbox-agent)

        (is (= num-tasks (-> task-id->sandbox-in-db (merge task-id->sandbox-not-in-db) count)))
        (doseq [[task-id _] task-id->sandbox-not-in-db]
          (is (= (task-id->sandbox task-id) (retrieve-sandbox db-conn task-id))))
        (doseq [[task-id _] task-id->sandbox-in-db]
          (is (= (task-id->sandbox task-id) (retrieve-sandbox db-conn task-id))))))))

(deftest test-start-sandbox-publisher
  (let [db-conn (tu/restore-fresh-database! "datomic:mem://test-start-sandbox-publisher")
        publish-batch-size 20
        publish-interval-ms 10
        num-publishes 4
        latch (CountDownLatch. num-publishes)
        task-id->sandbox-publish-history-atom (atom [])
        task-id->sandbox-state {:a 1, :b 2, :c 3}
        task-id->sandbox-agent (agent task-id->sandbox-state)]
    (with-redefs [sandbox/publish-sandbox-to-datomic!
                  (fn [datomic-conn batch-size task-id->sandbox-agent]
                    (is (= db-conn datomic-conn))
                    (is (= publish-batch-size batch-size))
                    (swap! task-id->sandbox-publish-history-atom conj @task-id->sandbox-agent)
                    (.countDown latch)
                    (send task-id->sandbox-agent sandbox/clear-agent-state @task-id->sandbox-agent)
                    (await task-id->sandbox-agent)
                    (Thread/sleep publish-interval-ms))]

      (let [cancel-fn (sandbox/start-sandbox-publisher
                        task-id->sandbox-agent db-conn publish-batch-size publish-interval-ms)]
        (.await latch 10 TimeUnit/SECONDS)
        (cancel-fn)

        (is (= {} @task-id->sandbox-agent))
        (is (<= num-publishes (count @task-id->sandbox-publish-history-atom) (inc num-publishes)))
        (is (= task-id->sandbox-state (first @task-id->sandbox-publish-history-atom)))
        (is (every? empty? (rest @task-id->sandbox-publish-history-atom)))))))

(deftest test-retrieve-sandbox-directories-on-agent
  (let [target-framework-id "framework-id-11"
        agent-hostname "www.mesos-agent-com"]
    (with-redefs [http/get (fn [url & [options]]
                             (is (= (str "http://" agent-hostname ":5051/state.json") url))
                             (is (= {:as :json-string-keys, :conn-timeout 5000, :socket-timeout 5000, :spnego-auth true} options))
                             {:body
                              {"completed_frameworks"
                               [{"completed_executors" [{"id" "executor-000", "directory" "/path/for/executor-000"}]
                                 "executors" [{"id" "executor-005", "directory" "/path/for/executor-005"}]
                                 "id" "framework-id-00"}
                                {"completed_executors" [{"id" "executor-010", "directory" "/path/for/executor-010"}]
                                 "executors" [{"id" "executor-015", "directory" "/path/for/executor-015"}]
                                 "id" "framework-id-01"}]
                               "frameworks"
                               [{"completed_executors" [{"id" "executor-101", "directory" "/path/for/executor-101"}
                                                        {"id" "executor-102", "directory" "/path/for/executor-102"}]
                                 "executors" [{"id" "executor-111", "directory" "/path/for/executor-111"}]
                                 "id" target-framework-id}
                                {"completed_executors" [{"id" "executor-201", "directory" "/path/for/executor-201"}]
                                 "executors" [{"id" "executor-211", "directory" "/path/for/executor-211"}]
                                 "id" "framework-id-12"}]}})]

      (testing "retrieve-sandbox-directories-on-agent"
        (let [actual-result (sandbox/retrieve-sandbox-directories-on-agent target-framework-id agent-hostname)
              expected-result {"executor-101" "/path/for/executor-101"
                               "executor-102" "/path/for/executor-102"
                               "executor-111" "/path/for/executor-111"}]
          (is (= expected-result actual-result)))))))

(deftest test-refresh-agent-cache-entry
  (let [db-conn (tu/restore-fresh-database! "datomic:mem://test-refresh-agent-cache-entry")
        framework-id "test-framework-id"
        mesos-agent-query-cache (atom (cache/fifo-cache-factory {} :threshold 2))
        task-id->sandbox-agent (agent {})
        item-unavailable (future {:result :unavailable})
        publisher-state {:mesos-agent-query-cache mesos-agent-query-cache
                         :task-id->sandbox-agent task-id->sandbox-agent}
        refresh-agent-cache-helper #(sandbox/refresh-agent-cache-entry publisher-state framework-id %)
        task-ids-with-sandbox-in-db ["task2.host1" "task2.host2" "task2.host3" "task3.host3"]
        lookup-host-state (fn [hostname]
                            (-> @mesos-agent-query-cache
                                (cache/lookup hostname item-unavailable)
                                deref))
        lookup-host-state-result (fn [hostname] (:result (lookup-host-state hostname)))
        lookup-host-state-data (fn [hostname] (:data (lookup-host-state hostname)))
        hostname->task-id->sandbox-directory (fn [hostname]
                                               {(str "task1." hostname) (str "/path/to/1/" hostname "/sandbox")
                                                (str "task2." hostname) (str "/path/to/2/" hostname "/sandbox")
                                                (str "task3." hostname) (str "/path/to/3/" hostname "/sandbox")})]

    (doseq [task-id task-ids-with-sandbox-in-db]
      (tu/create-dummy-instance db-conn (tu/create-dummy-job db-conn)
                                :sandbox-directory (str "path/to/" task-id "/directory")
                                :task-id task-id))

    (with-redefs [sandbox/retrieve-sandbox-directories-on-agent
                  (fn [_ hostname]
                    (if (str/includes? hostname "badhost")
                      (throw (Exception. "Exception from test"))
                      (hostname->task-id->sandbox-directory hostname)))]

      (testing "cache population on good hosts"
        (refresh-agent-cache-helper "host1")
        (refresh-agent-cache-helper "host2")
        (await task-id->sandbox-agent)
        (is (= :success (lookup-host-state-result "host1")))
        (is (= (hostname->task-id->sandbox-directory "host1") (lookup-host-state-data "host1")))
        (is (= :success (lookup-host-state-result "host2")))
        (is (= (hostname->task-id->sandbox-directory "host2") (lookup-host-state-data "host2")))
        (is (= :unavailable (lookup-host-state-result "host3")))
        (is (= :unavailable (lookup-host-state-result "badhost")))
        (is (= {} @task-id->sandbox-agent)))

      (testing "cache eviction on good host"
        (refresh-agent-cache-helper "host3")
        (await task-id->sandbox-agent)
        (is (= :unavailable (lookup-host-state-result "host1")))
        (is (= :success (lookup-host-state-result "host2")))
        (is (= (hostname->task-id->sandbox-directory "host2") (lookup-host-state-data "host2")))
        (is (= :success (lookup-host-state-result "host3")))
        (is (= (hostname->task-id->sandbox-directory "host3") (lookup-host-state-data "host3")))
        (is (= :unavailable (lookup-host-state-result "badhost")))
        (is (= {} @task-id->sandbox-agent)))

      (testing "cache eviction on bad host"
        (refresh-agent-cache-helper "badhost")
        (await task-id->sandbox-agent)
        (is (= :unavailable (lookup-host-state-result "host1")))
        (is (= :unavailable (lookup-host-state-result "host2")))
        (is (= :success (lookup-host-state-result "host3")))
        (is (= (hostname->task-id->sandbox-directory "host3") (lookup-host-state-data "host3")))
        (is (= :error (lookup-host-state-result "badhost")))
        (is (= {} @task-id->sandbox-agent)))

      (testing "syncing of cached host"
        (refresh-agent-cache-helper "host3")
        (await task-id->sandbox-agent)
        (is (= :unavailable (lookup-host-state-result "host1")))
        (is (= :unavailable (lookup-host-state-result "host2")))
        (is (= :success (lookup-host-state-result "host3")))
        (is (= (hostname->task-id->sandbox-directory "host3") (lookup-host-state-data "host3")))
        (is (= :error (lookup-host-state-result "badhost")))
        (is (= {} @task-id->sandbox-agent))))))

(deftest test-prepare-sandbox-publisher
  (with-redefs [sandbox/retrieve-sandbox-directories-on-agent
                (fn [_ hostname]
                  {(str "task." hostname) (str "/path/to/" hostname "/sandbox")})]
    (let [db-conn (tu/restore-fresh-database! "datomic:mem://test-start-sandbox-publisher")
          publish-batch-size 20
          publish-interval-ms 10
          framework-id "test-framework-id"
          mesos-agent-query-cache (atom (cache/fifo-cache-factory {} :threshold 2))
          {:keys [publisher-cancel-fn task-id->sandbox-agent] :as sandbox-state}
          (sandbox/prepare-sandbox-publisher
            framework-id db-conn publish-batch-size publish-interval-ms mesos-agent-query-cache)]

      (try
        (->> {"sandbox-directory" "/path/to/sandbox", "task-id" "task-1", "type" "directory"}
             (sandbox/update-sandbox sandbox-state))

        @(sandbox/sync-agent-sandboxes sandbox-state framework-id "host1")
        (await task-id->sandbox-agent)
        (is (= {"task-1" "/path/to/sandbox"} @task-id->sandbox-agent))

        (send task-id->sandbox-agent sandbox/aggregate-sandbox "task-2" "/path/to/task-2/sandbox")
        (await task-id->sandbox-agent)
        (is (= {"task-1" "/path/to/sandbox", "task-2" "/path/to/task-2/sandbox"} @task-id->sandbox-agent))
        (finally
          (publisher-cancel-fn))))))
